import os
from datetime import date
import time
import signal
from threading import Lock
import re


from lxml import etree
from tqdm import tqdm

from crawler import HtmlCrawler, WebpCrawler, HtmlTSLCrawler
from tools import retry, count_sleep, get_subdir
from playwright_tool import login
from jmtools import JMImgHandle, JMDirHandle, extract_and_combine_numbers, log_filter_fail_id
from jmconfig import cfg, down_queue
from jmlogger import logger
from database.models import Comic
from database.database import db
from database.crud import (add_comic,
                           query_comic,
                           query_static,
                           search_data_to_db,
                           home_data_to_db,
                           page_data_to_db)
from threadingpool import MyTheadingPool, Future


# TODO git创建分支再提交，测试完成再合并
# TODO 使用线程池
# TODO 使用数据库
# TODO 新增队列任务，流程 comicid -> 主页，获取信息入库 -> 添加任务队列 -> 线程池下载

TMP_DIR = os.path.join('.', 'tmp')
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)


class JMSpider:
    """禁漫爬虫

    通过禁漫的漫画id进行爬取，
    内容保存到以 "id-漫画标题" 格式的目录中
    """

    _transform_id = 220981  # 从这个id开始，图片都是乱序的，怎么得来的？一个个顺序排查的
    # _headers = {'user-agent': 'PostmanRuntime/7.34.0', }
    _headers = {'user-agent': 'PostmanRuntime/7.36.1'}
    _root_url = 'https://18comic.org/'

    def __init__(self) -> None:
        self.cfg = cfg
        self.db = db
        self.queue_lock = Lock()
        self.pool = MyTheadingPool()
        self.down_queue = {'home': [], 'page': [], 'img': {}}

    def update_cookies(self) -> bool:
        """自动登录，获取cookie写入配置中

        Returns:
            bool: 是否登录成功
        """
        username = self.cfg.get('username', '')
        password = self.cfg.get('password', '')
        if username and password:
            logger.info('开始更新cookie')
            try:
                cookie = login(username, password)
                self.cfg['cookie'] = cookie
                self.cfg['cookie_update'] = str(date.today())
                logger.info(f'cookie更新完毕: {self.cfg["cookie"]}')
                return True
            except Exception as e:
                logger.info(f'cookie更新失败, [error]: {e}')

        return False

    def is_need_login(self) -> bool:
        """判断是否需要登录
        cookie有效期应该有180天
        这里现在设定每天都登录，只要登录日期不是今天都需要更新

        Returns:
            bool: 是否需要更新
        """
        return not (str(date.today()) == self.cfg.get('cookie_update', ''))

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_comic_page(cls, comicid: str, save_file: str, cookies: dict = None, page: int = None) -> bool:
        """下载漫画页面

        Args:
            comicid (str): 漫画id
            save_file (str): 保存文件
            cookies (dict, optional): 登录cookie. Defaults to None.
            page (int, optional): 下载哪一页. Defaults to None.

        Returns:
            bool: _description_
        """
        if not cookies:
            cookies = {}

        params = {}
        if page:
            params = {
                'page': '{}'.format(page),
            }

        hc = HtmlCrawler(
            url='https://18comic.org/photo/{}'.format(comicid),
            cookies=cookies,
            headers=cls._headers,
            params=params
        )

        return hc.get(save_file)

    @classmethod
    def parse_comic_page(cls, html_file: str) -> dict:
        """解析漫画页面数据

        Args:
            html_file (str): 网页文件

        Returns:
            dict: 解析数据
        """

        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()
        root_element = etree.HTML(html)
        ret_data = {}

        # 所有图片url
        urls = root_element.xpath(
            '//div[@class="center scramble-page"]/img/@data-original')
        ret_data['urls'] = urls

        # 漫画标题
        title = root_element.xpath(
            '//div[@class="container"]/div[@class="row"]/div/div[@class="panel panel-default"]/div[@class="panel-heading"]/div[@class="pull-left"]/text()')
        if title:
            title = title[0].replace('\n', '').strip()
            ret_data['title'] = title

        # 下一话id
        next_comic = root_element.xpath(
            '//i[@class="fas fa-angle-double-right"]/../@href')
        if next_comic:
            next_comic = next_comic[0].split('/')[-1].split('?')[0]
            ret_data['next_comic'] = next_comic

        # 获取最大页数
        # 如果当前页面是最后一页，统计该漫画有多少页
        curr_page = root_element.xpath(
            '//div[@class="hidden-xs"]/ul[@class="pagination"]/li')
        if curr_page:
            # 当前页面如果是最后一页，会少一个跳到尾部的li标签，所以直接判断最后一个
            if curr_page[-1].attrib.get('class', None):
                max_page = curr_page[-1].xpath('span/text()')
                ret_data['max_page'] = int(max_page[0])
                ret_data['curr_page'] = len(
                    ret_data['urls']) + (ret_data['max_page'] - 1) * 300
            else:
                # 不在最后一页，尾部会多个跳到尾部的li标签，所以倒数第二个才是最大页数
                max_page = curr_page[-2].xpath('a/text()')
                ret_data['max_page'] = int(max_page[0])
                ret_data['curr_page'] = 0
        else:  # 没有该标签表示没有分页
            ret_data['curr_page'] = len(ret_data['urls'])
            ret_data['max_page'] = 1

        # 获取介绍页面链接
        home_url = root_element.xpath(
            '//*[@id="wrapper"]/div[7]/ul[2]/li[6]/a/@href')
        if home_url:
            ret_data['home_url'] = ''.join((cls._root_url, home_url[0]))

        return ret_data

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_comic_img(cls, url: str, save_file: str) -> bool:
        """下载图片

        Args:
            url (str): 图片url
            save_file (str): 保存的文件路径

        Returns:
            bool: 是否成功
        """
        wc = WebpCrawler(url, headers=cls._headers)
        return wc.get(save_file)

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_search_page(cls, page: int, search: str, save_file: str, cookies: dict = None) -> bool:
        """下载搜索页面

        Args:
            page (int): 获取搜索结果的哪一页
            search (str): 搜索内容
            save_file (str): 提供网页文件保存位置
            cookies (dict, optional): 登录cookie. Defaults to None.

        Returns:
            bool: 是否成功
        """

        if not cookies:
            cookies = {}
        cookies['_gali'] = 'wrapper'

        '''
        参数
        o 排序: tf 点赞最多，mp 图片最多，mv 阅读最多， mr 最新的(默认)
        发布时间 t: t 今天，w 这周，m 本月，a 全部(默认)
        '''
        params = {
            'main_tag': '0',
            'search_query': search,
            'page': '{}'.format(page),
        }

        hc = HtmlCrawler(url='https://18comic.org/search/photos',
                         params=params,
                         headers=cls._headers,
                         cookies=cookies
                         )
        return hc.get(save_file)

    @retry(sleep=1)
    @count_sleep
    def download_home_page(self, url: str, save_file: str, cookies: dict = None) -> bool:
        """下载comic详情页
        处理需要TSL指纹反爬的请求

        Args:
            url (str): 请求链接
            save_file (str): 指定保存的文件
            cookies (dict, optional): 添加登录cookie. Defaults to None.

        Returns:
            bool: 是否成功
        """
        if not cookies:
            cookies = {}
        cookies['_gali'] = 'wrapper'

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,'
            'application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'zh-CN,zh;q=0.9',
            'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 '
                      'Safari/537.36',
            'authority': '18comic.vip',
            'origin': 'https://18comic.vip',
            'referer': 'https://18comic.vip'
        }
        proxies = self.cfg.get('proxies', None)

        hc = HtmlTSLCrawler(url=url,
                            headers=headers,
                            cookies=cookies,
                            proxies=proxies
                            )
        return hc.get(save_file)

    def parse_home_page(self, html_file: str) -> dict:
        """解析主页数据

        Args:
            html_file (str): 网页文件

        Returns:
            dict: 解析结果
        """
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()

        root_element = etree.HTML(html)
        res_list = {}

        res_list['url'] = ''
        url = root_element.xpath('//*[@property="og:url"]/@content')
        if url:
            res_list['url'] = url[0]

        res_list['title'] = ''
        title = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[1]/div[1]/h1/text()')
        if title:
            res_list['title'] = title[0]

        res_list['comicid'] = ''
        comicid = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[1]/div[1]/text()')
        if comicid:
            comp = re.compile(r'JM(\d+)')
            res = re.findall(comp, comicid[0])
            if res:
                res_list['comicid'] = res[0]

        res_list['tags'] = None
        tags = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[1]/div[4]/span/a/text()')
        if tags:
            res_list['tags'] = tags

        res_list['author'] = None
        author = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[1]/div[5]/span/a/text()')
        if author:
            res_list['author'] = author

        res_list['description'] = ''
        description = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[1]/div[8]/text()')
        if description:
            comp = re.compile(r'敘述：(.*)', re.DOTALL)
            res = re.findall(comp, description[0])
            if res:
                res_list['description'] = res[0]

        res_list['page'] = 0
        page = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[1]/div[9]/text()')
        if page:
            comp = re.compile(r'頁數：(\d+)')
            res = re.findall(comp, page[0])
            if res:
                res_list['page'] = int(res[0])

        res_list['next'] = None
        next = root_element.xpath(
            '//*[@id="wrapper"]/div[5]/div[4]/div/div[2]/div[2]/div/div[2]/div[3]/div/ul/a/@data-album')
        if next:
            res_list['next'] = next

        return res_list

    @classmethod
    def parse_search_page(cls, html_file: str, filter: list = None) -> list:
        """解析搜索页面

        Args:
            html_file (str): 网页文件
            filter (list, optional): 过滤tag. Defaults to None.

        Returns:
            list: 解析结果 [[漫画id, 漫画主页链接],...]
        """

        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()

        root_element = etree.HTML(html)
        res_list = []
        divs_1 = root_element.xpath('//div[@class="row m-0"]/div')
        divs_2 = root_element.xpath(
            '//div[@class="container"]/div[3]/div/div/div')
        if divs_2:
            divs_1.extend(divs_2)

        for i in divs_1:
            comic_url = i.xpath('div/a/@href')
            if not comic_url:
                continue
            comicid = comic_url[0].split('/')[-2]
            comic_url = ''.join((cls._root_url, comic_url[0]))

            # 判断是否过滤
            if filter:
                a_tags = i.xpath('div/div[2]//a/text()')
                if set(filter) & set(a_tags):
                    continue
            res_list.append([comicid, comic_url])

        return res_list

    @staticmethod
    def parse_search_total_page(html_file: str) -> int:
        """解析搜索页面的页数

        Args:
            html_file (str): 网站文件

        Returns:
            int: 总页数
        """
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()
        root_element = etree.HTML(html)
        page = root_element.xpath('//ul[@class="pagination"]/li[8]/a/text()')
        if page:
            return int(page[0])
        return 1

    def stop_signal_handler(self, signum, frame):
        """Ctrl + C信号处理函数，暂停下载任务

        Args:
            signum (_type_): _description_
            frame (_type_): _description_
        """
        logger.info('接收到 Ctrl + C 信号')
        self.stop_flag = True

    def download_comic_2(self) -> None:
        """漫画下载

        对数据库中static==0的漫画进行检查数据是否完整
        page==0 进行主页数据获取
        curr_page==0 进行页数数据获取
        根据curr_page检查漫画目录的图片数量是否一致
        """
        comics = query_static(self.db, 0)
        for comic in comics:
            self.check_comic(comic.comicid)


        time.sleep(5)
        while self.down_queue:
            self.pool.wait()
            time.sleep(5)

        self.pool.close()
        print(self.down_queue)

    def check_comic(self, comicid):
        """检查漫画缺少的数据，并下载

        Args:
            comicid (_type_): 漫画id
        """
        comic = query_comic(self.db, comicid)
        if comic:
            if comic.page == 0:
                # 是否获取主页数据
                self.check_home(comic)
            if comic.curr_page == 0:
                # 是否获取页面数据
                self.check_page(comic)
            else:
                # 是否需要下载图片
                self.check_img(comic)

    def check_home(self, comic: Comic):
        """检查该漫画主页数据是否需要下载，需要则添加线程

        Args:
            comicid (str): 漫画id
        """
        if comic \
            and comic.url != '' \
            and comic.page == 0 \
            and comic.comicid not in self.down_queue['home']:

            with self.queue_lock:
                self.down_queue['home'].append(comic.comicid)
            task = self.pool.add_task(
                self.work_home_data, comic.comicid, comic.url)
            if task:
                logger.info(f'{comic.comicid} 下载主页数据')
                task.add_done_callback(self.callback_download)

    def check_page(self, comic: Comic):
        """检查该漫画页数数据是否需要下载，需要则添加线程

        Args:
            comicid (str): 漫画id
        """
        if comic \
            and comic.curr_page == 0 \
            and comic.comicid not in self.down_queue['page']:

            with self.queue_lock:
                self.down_queue['page'].append(comic.comicid)
            task = self.pool.add_task(self.work_page_data, comic.comicid)
            if task:
                logger.info(f'{comic.comicid} 下载页数数据')
                task.add_done_callback(self.callback_download)

    def check_img(self, comic: Comic):
        """检查该漫画图片文件是否需要下载，需要则添加线程

        Args:
            comic (Comic): 漫画id
        """

        if comic \
            and comic.curr_page != 0 \
            and comic.static == 0 \
            and comic.comicid not in self.down_queue['img']:

            with self.queue_lock:
                self.down_queue['img'][comic.comicid] = 0

            is_complet = True
            # https://cdn-msp2.18comic.org/media/photos/551644/00001.webp
            base_url = 'https://cdn-msp2.18comic.org/media/photos/{}/{:05d}.webp'
            for i in range(comic.curr_page):
                url = base_url.format(comic.comicid, i+1)
                comic_dir = self.get_comic_dir(
                    comic.comicid, comic.chapter_titile)
                img_path = JMDirHandle.get_img_path(url, comic_dir)
                if not os.path.exists(img_path): # 文件不存在则下载
                    with self.queue_lock:
                        self.down_queue['img'][comic.comicid] += 1

                    if is_complet: # 只触发一次
                        logger.info(f'{comic.comicid} 下载图片文件')
                    is_complet = False

                    task = self.pool.add_task(
                        self.work_img, comic.comicid, img_path, url)
                    if task:
                        task.add_done_callback(self.callback_img)

            if is_complet:
                with self.queue_lock:
                    del self.down_queue['img'][comic.comicid]
                comic.static = 1
                add_comic(self.db, comic)

    def check_next(self, comicid: str):
        """检查漫画是否有下一话，有的话对其进行检查

        Args:
            comicid (str): _description_
        """
        comic = query_comic(self.db, comicid)
        if comic:
            next = comic.next.split(' ')  # 空字符串会返回['']
            # 当前id是第一章时，才进行检查后面章节，这样可以减少重复步骤
            if comicid == next[0]:
                for i in next[1:]:
                    self.check_comic(i)

    def work_img(self, comicid: str, img_path: str, url: str) -> str:
        """线程函数，下载图片

        Args:
            comicid (str): 漫画id
            img_path (str): 图片路径
            url (str): 图片链接
        
        Returns:
            str: 漫画id
        """
        try:
            res = self.download_comic_img(url, img_path)
            if res:
                # 还原下载的图片
                if int(comicid) >= self._transform_id:
                    JMImgHandle.restore_img(comicid, os.path.basename(
                        img_path).split('.')[0], img_path)
            else:
                logger.info(f'{comicid} 下载图片失败, [url]: {url}')
        except Exception as e:
            logger.info(
                f'{comicid} 下载图片发生错误[url]: {url}, [error]: {e}')

        with self.queue_lock:
            self.down_queue['img'][comicid] -= 1

        return comicid

    def work_page_data(self, comicid: str) -> str:
        """下载漫画页面数据并添加到数据库
        线程函数

        Args:
            comicid (str): 漫画id
        
        Returns:
            str: 漫画id
        """
        is_error = False
        tmp_file = os.path.join(TMP_DIR, f'{comicid}_page.html')
        try:
            res = self.download_comic_page(
                comicid, tmp_file, self.cfg.get('cookie', None))
            if res:
                page_data = self.parse_comic_page(tmp_file)
                # 漫画超过300张会分页显示，不利于统计，需要获取最后一页统计
                # 这里直接获取后一页，然后通过计算得出这部漫画有多少张图片
                if page_data['max_page'] > 1:
                    res = self.download_comic_page(comicid, tmp_file, self.cfg.get(
                        'cookie', None), page_data['max_page'])
                    if res:
                        page_data = self.parse_comic_page(tmp_file)
                    else:
                        is_error = True

                if not is_error:
                    page_data_to_db(self.db, comicid, page_data)
                    logger.info(f'{comicid} 下载页数数据成功。')
        except Exception as e:
            logger.error(f'{comicid} 下载页数数据出错。error:{e}')
        finally:
            if os.path.exists(tmp_file):
                os.unlink(tmp_file)

        with self.queue_lock:
            self.down_queue['page'].remove(comicid)

        return comicid

    def work_home_data(self, comicid: str, url: str) -> str:
        """下载漫画主页数据并添加到数据库
        线程函数

        Args:
            comicid (str): 漫画id
            url (str): 主页链接

        Returns:
            str: 漫画id
        """
        tmp_file = os.path.join(TMP_DIR, f'{comicid}_home.html')
        try:
            res = self.download_home_page(
                url, tmp_file, self.cfg.get('cookie', None))
            if res:
                home_data = self.parse_home_page(tmp_file)
                home_data_to_db(self.db, home_data)
                logger.error(f'{comicid} 下载主页数据成功。')
        except Exception as e:
            logger.error(f'{comicid} 下载主页数据出错。error:{e}')
        finally:
            if os.path.exists(tmp_file):
                os.unlink(tmp_file)

        with self.queue_lock:
            self.down_queue['home'].remove(comicid)

        return comicid

    def callback_download(self, future: Future):
        """回调函数，主页数据和页面数据线程callbakc
        判断漫画缺少哪些数据就补齐那部分的数据

        Args:
            future (Future): 线程对象
        """
        comicid = future.result()
        self.check_comic(comicid)
        self.check_next(comicid)
    
    def callback_img(self, future: Future):
        """回调函数，清空图片队列并对漫画图片进行一次检查

        Args:
            future (Future): 线程对象
        """
        comicid = future.result()
        with self.queue_lock:
            if self.down_queue['img'][comicid] <= 0:
                del self.down_queue['img'][comicid]
                self.check_img(comicid)

    def download_comic(self, comicids: list) -> None:
        """漫画下载

        流程
        1. 下载漫画页面
        2. 提取页面的图片url, 标题, 总页数, 下一话
        3. 判断该页面是否有下一页, 有则重复第一步
        4. 下载所有图片url
        5. 还原下载的图片
        6. 判断是否有下一话, 有则添加到comicids第一位
        """
        if not comicids:
            logger.info('[function]:download_comic, [error]:传入参数有误')
            return

        cookies = self.cfg.get('cookie', {})
        save_dir = self.cfg.get('save_dir', os.path.abspath('.'))
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        self.stop_flag = False
        old_handler = signal.signal(signal.SIGINT, self.stop_signal_handler)

        while comicids:
            download_urls = []
            download_id = comicids.pop(0)
            if not download_id:
                continue

            if download_id not in self.cfg['redownloading']:
                self.cfg['redownloading'].append(download_id)
                self.cfg.save()

            start_time = time.time()
            logger.info(f'开始下载: {download_id}')

            # 1. 下载漫画页面
            current_page = 1
            page_data = None
            comic_page_html = os.path.join(
                save_dir, f'{download_id}.html')  # 临时文件
            while True:
                res = self.download_comic_page(download_id,
                                               comic_page_html,
                                               cookies,
                                               page=None if current_page == 1 else current_page
                                               )
                if not res:
                    logger.info(f'下载网页失败: {download_id}')
                    break

                # 2. 提取页面的图片url,和其他数据
                data = self.parse_comic_page(comic_page_html)
                if page_data == None:  # 数据保存一次就行，urls另外储存
                    page_data = data
                if not data.get('title', False):
                    logger.info(
                        f'{download_id} [page]:{current_page}, [error]:解析网页出错，可能该id失效，或需要登录')
                    break
                download_urls.extend(data.get('urls', []))

                # 3. 判断是否有下一页
                if current_page >= page_data.get('max_page', 1):
                    break
                current_page += 1

            if os.path.exists(comic_page_html):
                os.remove(comic_page_html)

            # 需要title的数据创建目录
            if page_data != None and page_data.get('title', False):
                # 4. 下载所有图片url
                comic_dir = JMDirHandle.create_comic_dir(
                    download_id, page_data['title'], save_dir)
                for url in tqdm(download_urls):
                    try:
                        img_path = JMDirHandle.get_img_path(url, comic_dir)
                        if os.path.exists(img_path):
                            continue
                        res = self.download_comic_img(url, img_path)
                        if res:
                            # 5. 还原下载的图片
                            if int(download_id) >= self._transform_id:
                                JMImgHandle.restore_img(download_id, os.path.basename(
                                    img_path).split('.')[0], img_path)
                        else:
                            if download_id not in self.cfg['redownload']:
                                self.cfg['redownload'].append(download_id)
                                self.cfg.save()
                            logger.info(f'{download_id} 下载图片失败, [url]: {url}')
                    except Exception as e:
                        if download_id not in self.cfg['redownload']:
                            self.cfg['redownload'].append(download_id)
                            self.cfg.save()
                        logger.info(
                            f'{download_id} 下载图片发生错误[url]: {url}, [error]: {e}')

                    if self.stop_flag:
                        break

                # 6. 判断是否有下一话
                if page_data.get('next_comic', None) and (page_data["next_comic"] not in comic_dir):
                    comicids.insert(0, page_data["next_comic"])
                    logger.info(f'{page_data["next_comic"]} 追加到下载任务')

                if (not self.stop_flag) and (download_id in self.cfg['redownloading']):
                    self.cfg['redownloading'].remove(download_id)
                    self.cfg.save()
                end_time = time.time()
                logger.info(
                    f'下载完成: {download_id}, 花费时间: {end_time - start_time:.2f}秒')

            if self.stop_flag:
                signal.signal(signal.SIGINT, old_handler)
                logger.info('下载被 Ctrl+C 中断')
                break

    def run(self) -> None:
        """漫画下载入口
        """

        # 检查漫画文件是否缺失
        if self.cfg['is_check']:
            self.check_comic_complet()

        # 处理重新下载的漫画
        if self.cfg['is_redownload']:
            self.redownload()

        # 检查下载文件是否存在
        download_file = self.cfg.get('download_file', '')
        if (not download_file) or (not os.path.exists(download_file)):
            logger.info(f'download_file不存在: {download_file}')
            return

        # 读取已经下载的id，避免重复下载
        ids = JMDirHandle.get_dirs_comicid(
            self.cfg.get('filter_dir', []))
        filter_ids = JMDirHandle.comicid_fliter(set(ids))
        if filter_ids:
            logger.info(f'读取过滤id成功')
            try:
                next(filter_ids)
            except StopIteration:
                filter_ids = None
        else:
            logger.info(f'读取过滤id失败')

        # 文件中读取要下载的id
        ids = []
        with open(download_file, 'r', encoding='utf-8') as f:
            line = f.readline()
            while line:
                line = line.rstrip('\n')
                for i in line.split(' '):
                    if (not i) or (i in ids) or (filter_ids and filter_ids.send(i)):
                        continue
                    ids.append(i)
                line = f.readline()

        if self.cfg['is_update_cookie'] and self.is_need_login():
            self.update_cookies()

        self.download_comic(ids)

    def search(self, key: str, max: int = 0):
        """搜索，结果保存到数据库
        """
        cookies = self.cfg.get("cookie", None)
        html_file = "search.html"
        page = 1
        max_page = 1

        logger.info(f'开始搜索[{key}]')
        with tqdm() as pbar:
            while True:
                res = self.download_search_page(
                    page=page, search=key, cookies=cookies, save_file=html_file)
                if res:
                    if max_page == 1:
                        max_page = self.parse_search_total_page(html_file)
                        pbar.total = max_page
                        if max > 0 and max_page > max:
                            logger.info(f'搜索结果共{max_page}页, 只获取{max}页')
                            max_page = max
                        else:
                            logger.info(f'搜索结果共{max_page}页')

                    search_data = self.parse_search_page(
                        html_file, self.cfg.get('filter_tag', None))
                    search_data_to_db(self.db, search_data)

                else:
                    logger.info(f'获取搜索页面失败 [key]:{key}, [page]:{page}')

                pbar.update(1)

                if page >= max_page:
                    break
                page += 1

        if os.path.exists(html_file):
            os.unlink(html_file)
        logger.info(f'搜索[{key}]完成')

    def del_blacklist(self):
        """删除黑名单的内容，但是保留带comicid的目录
        """
        dir = self.cfg.get('blacklist', None)
        if dir:
            JMDirHandle.comic_clean(dir)

    def save_idfile(self, ids: list) -> None:
        '''把id写入ids文件
        '''
        savefile = self.cfg.get('download_file', '')
        if not savefile:
            savefile = 'data/ids.txt'
            self.cfg['download_file'] = savefile

        if not os.path.exists(savefile):
            # 快速创建空文件
            with open(savefile, 'w', encoding='utf-8'):
                pass

        with open(savefile, 'r+', encoding='utf-8') as f:
            content = f.readline()
            while content:
                ids.extend(content.replace('\n', '').split(' '))
                content = f.readline()
            f.seek(0)
            f.truncate(0)
            ids = [val for index, val in enumerate(
                ids) if ids.index(val) == index]
            for i in range(0, len(ids), 50):
                f.write(' '.join(ids[i:i+50]))
                f.write('\n')

    def zip_comic(self, comicids: list) -> list:
        '''根据id列表打包漫画
        '''
        if not comicids:
            return []
        comicids = list(set(comicids))
        dirs = self.cfg.get('filter_dir', [])
        zip_dirs = JMDirHandle.get_comics_dirs(comicids, dirs)
        if comicids:
            logger.info(f'打包过程中，出现找到对应的文件 {" ".join(comicids)}')
        out_file = self.cfg.get('out_zip', 'jmcomic.zip')
        JMDirHandle.zip_dir(zip_dirs, out_file)

    def redownload(self) -> None:
        '''读取要重新下载的id进行下载
        '''
        ids = self.cfg.get('redownload', [])
        redownload_ids = self.cfg.get('redownloading', [])
        if not ids and not redownload_ids:
            return

        redownload_ids.extend(ids)
        redownload_ids = list(set(redownload_ids))
        self.cfg['redownloading'] = redownload_ids
        self.cfg['redownload'] = []
        self.download_comic(redownload_ids)

    def check_comic_complet(self):
        """检查漫画目录是否完成
        漫画目录是通过配置的 filter_dir 读取，
        将需重新下载漫画添加到配置的redownloading中
        """
        check_count = 0
        count = 0
        for dir in self.cfg['filter_dir']:
            for subdir in get_subdir(dir):
                res = JMDirHandle.simple_check_comic(subdir)
                if not res:
                    check_count += 1
                    res = JMDirHandle.dir_to_comicid(subdir)
                    if res:
                        self.cfg['redownloading'].append(res)
                        self.cfg.save()
                        count += 1
        logger.info(f'检查{check_count}个有问题，添加到下载{count}个')

    def get_comic_dir(self, comicid: str, title: str) -> str:
        """根据id和标题返回文件夹

        Args:
            comicid (str): 漫画id
            title (str): 漫画标题(数据库的chapter_titile列)
        """
        save_dir = self.cfg.get('save_dir', os.path.abspath('.'))
        return JMDirHandle.create_comic_dir(comicid, title, save_dir)


if __name__ == "__main__":
    pass
    jms = JMSpider()

    # 流程关键api测试
    # res = JMSpider.download_comic_page(comicid='521716', save_file='521716.html')
    # print(res)

    # res = JMSpider.download_comic_img('https://cdn-msp.18comic.org/media/photos/521716/00001.webp', '00001.webp')
    # print(res)

    # res = JMSpider.parse_comic_page('521716.html')
    # print(res)

    # res = JMSpider.download_search_page(1, '丝袜', save_file='search.html')
    # print(res)

    # jms.update_cookies()
    # jms.download_comic(['116501', '85831', '114097', '101747', '101340', '112748', '113504', '90521', '92095', '86744', '85574', '84580', '101717', '87156', '119542', '102229', '118333', '85605', '92680', '91723', '84323', '100691', '113912', '88304', '114016', '91284', '93207', '97309', '96746', '103314', '91666'])
    # jms.search('近親',max=5)
    # jms.run()
    # jms.del_blacklist()

    # 提取日志失败记录
    # print(log_filter_fail_id(r'data\jm_spider.log'))

    # TODO 模块化,命令行模式
    # 近親 NTR 母子 乱伦 亂倫 换母 亂交

    # 字符串提取comicid
    # jms.download_comic(extract_and_combine_numbers(''''''))
