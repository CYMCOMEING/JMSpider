import os
from datetime import date
import time
import signal
from threading import Lock
import re


from lxml import etree
from tqdm import tqdm

from crawler import HtmlCrawler, HtmlTSLCrawler, ImgTSLCrawler
from tools import retry, count_sleep, list_deduplication, clean_previous_line, traversal_dir, url_to_filename
from playwright_tool import login
from jmtools import JMImgHandle, JMDirHandle
from jmconfig import cfg
from jmlogger import logger
from database.models import *
from database.database import db
from database.crud import *
from threadingpool import MyTheadingPool, Future
from MySigint import MySigint


TMP_DIR = os.path.join('.', 'tmp')
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)


class JMSpider:
    """禁漫爬虫

    通过禁漫的漫画id进行爬取，
    内容保存到以 "id-漫画标题" 格式的目录中
    """

    _transform_id = 220981  # 从这个id开始，图片都是乱序的，怎么得来的？一个个顺序排查的
    # _headers = {'user-agent': 'PostmanRuntime/7.36.1'}
    _headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'}
    _root_url = 'https://18comic.org/'

    def __init__(self) -> None:
        self.cfg = cfg
        self.db = db
        self.pool = MyTheadingPool(max=5)
        self.queue_lock = Lock()  # 注意使用with只能操作self.task_queue，不能有其他代码，否则可能会死锁
        self.task_queue = {'comic': {}, 'chapter': {}, 'img': {}}
        self.success_count = 0
        # 下载优先级
        self.download_priority = sorted(
            [(k, v) for k, v in self.cfg['download_priority'].items()], key=lambda x: x[1])
        self.priority_func = {"comic": self.pop_comic_task_from_queue,
                              "chapter": self.pop_chapter_task_from_queue,
                              "img": self.pop_img_task_from_queue}
        self.download_content = self.cfg.get("download_content", {})

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
                logger.warning(f'cookie更新失败, [error]: {e}')

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

        # 上一话
        previous_comic = root_element.xpath(
            '//i[@class="fa fa-angle-double-left"]/../@href')
        if previous_comic:
            previous_comic = previous_comic[0].split('/')[-1].split('?')[0]
            ret_data['previous_comic'] = previous_comic

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
        ret_data['home_url'] = None
        home_url = root_element.xpath(
            '//div[@class="menu-bolock hidden-xs hidden-sm"]/ul[2]/li[6]/a/@href')
        if home_url and home_url[0] != 'javascript:void(0)':
            ret_data['home_url'] = ''.join((cls._root_url, home_url[0]))

        if not ret_data['home_url']:
            home_url = root_element.xpath(
                '//div[@class="menu-bolock hidden-xs hidden-sm"]/ul[2]/li[5]/a/@href')
            if home_url:
                ret_data['home_url'] = ''.join((cls._root_url, home_url[0]))

        return ret_data

    @retry(sleep=1)
    @count_sleep
    def download_comic_img(self, url: str, save_file: str) -> bool:
        """下载图片

        Args:
            url (str): 图片url
            save_file (str): 保存的文件路径

        Returns:
            bool: 是否成功
        """
        proxies = self.cfg.get('proxies', None)

        itc = ImgTSLCrawler(url=url,
                            headers=self._headers,
                            cookies=None,
                            proxies=proxies
                            )
        return itc.get(save_file)
        

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
        # if not cookies:
        #     cookies = {}
        # cookies['_gali'] = 'wrapper'

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
            '//div[@class="panel-heading"]/div[@itemprop="name"]/h1/text()')
        if title:
            res_list['title'] = title[0]

        res_list['comicid'] = None
        comicid = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[1]/div[1]/text()')
        if comicid:
            comp = re.compile(r'JM(\d+)')
            res = re.findall(comp, comicid[0])
            if res:
                res_list['comicid'] = int(res[0])

        res_list['tags'] = None
        tags = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[1]/div[4]/span[@data-type="tags"]/a/text()')
        if tags:
            res_list['tags'] = tags

        res_list['author'] = None
        author = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[1]/div[5]/span/a/text()')
        if author:
            res_list['author'] = author

        res_list['description'] = ''
        description = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[1]/div[8]/text()')
        if description:
            comp = re.compile(r'敘述：(.*)', re.DOTALL)
            res = re.findall(comp, description[0])
            if res:
                res_list['description'] = res[0]

        res_list['page'] = 0
        page = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[1]/div[9]/text()')
        if page:
            comp = re.compile(r'頁數：(\d+)')
            res = re.findall(comp, page[0])
            if res:
                res_list['page'] = int(res[0])

        res_list['next'] = None
        next = root_element.xpath(
            '//div[@class="panel-body"]/div/div[2]/div[3]/div//ul/a/@data-album')
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
        page = 1
        '''
        页数栏会根据不同页数发生变化，这里对每种变化都处理
        '''
        data = root_element.xpath('//ul[@class="pagination"]/li[8]/a/text()')
        if data and data[0] == '»':
            data = root_element.xpath(
                '//ul[@class="pagination"]/li[5]/a/text()')
        if data and data[0].isdecimal():
            page = int(data[0])

        data = root_element.xpath('//ul[@class="pagination"]/li[9]/a/text()')
        if data and data[0].isdecimal():
            if int(data[0]) > page:
                page = int(data[0])

        data = root_element.xpath(
            '//ul[@class="pagination"]/li[8]/span/text()')
        if data and data[0].isdecimal():
            if int(data[0]) > page:
                page = int(data[0])

        return page

    def work_img(self, comicid: int, url: str, img_path: str) -> dict:
        """下载图片线程函数

        Args:
            comicid (int): 漫画id
            url (str): 下载url

        Returns:
            dict: 返回{'comicid': 漫画id, 'type': 2, 'img_path':下载路径}
        """
        result = {'success': False, 'comicid': comicid, 'type': 2}
        is_fail = False
        try:
            res = self.download_comic_img(url, img_path)
            if res:
                # 还原下载的图片
                if comicid >= self._transform_id:
                    if r'.gif' != url[-4:]:  # 图片是gif格式的，不用还原
                        JMImgHandle.restore_img(str(comicid), os.path.basename(
                            img_path).split('.')[0], img_path)
            else:
                logger.warning(f'{comicid} 下载图片失败, [url]: {url}')
                is_fail = True
        except Exception as e:
            logger.warning(
                f'{comicid} 下载图片发生错误 [url]: {url}, [error]: {e}')
            is_fail = True

        if is_fail:
            comicimg = query_comicimg_by_url(self.db, comicid, url)
            page = query_comicimg_arr(self.db, comicimg, ComicImg.page)
            result['page'] = page[0]
            return result

        result['success'] = True
        return result

    def work_page_data(self, comicid: int) -> dict:
        """下载漫画页面数据并添加到数据库
        线程函数

        Args:
            comicid (int): 漫画id

        Returns:
            dict: 返回{'comicid': comicid, 'type': 1}
        """
        logger.info(f'{comicid} 下载页数数据')
        is_error = False
        tmp_file = os.path.join(TMP_DIR, f'{comicid}_page.html')
        result = {'success': False, 'comicid': comicid, 'type': 1}
        try:
            res = self.download_comic_page(
                str(comicid), tmp_file, self.cfg.get('cookie', None))
            if res:
                page_data = self.parse_comic_page(tmp_file)
                # 漫画超过300张会分页显示
                page = 1
                while page_data['max_page'] > page:
                    page += 1
                    res = self.download_comic_page(str(comicid), tmp_file, self.cfg.get(
                        'cookie', None), page)
                    if res:
                        tmp_data = self.parse_comic_page(tmp_file)
                        page_data['urls'].extend(tmp_data['urls'])
                        page_data['curr_page'] = len(page_data['urls'])
                    else:
                        is_error = True

                # 等获取最大页数才记录数据
                if not is_error:
                    if page_data['curr_page'] == 0:
                        raise ValueError(f'{comicid} 页面解析出错')
                    self.page_data_to_db(comicid, page_data)
                    logger.info(f'{comicid} 下载页数数据成功。')

        except Exception as e:
            logger.error(f'{comicid} 页面可能不存在或者需要登录。error:{e}')
            return result
        finally:
            if os.path.exists(tmp_file):
                os.unlink(tmp_file)

        result['success'] = True
        return result

    def work_home_data(self, comicid: int, url: str) -> dict:
        """下载漫画主页数据并添加到数据库
        线程函数

        Args:
            comicid (int): 漫画id
            url (str): 主页链接

        Returns:
            dict: 返回{'comicid': 漫画id, 'type':0}
        """
        logger.info(f'{comicid} 下载主页数据')
        tmp_file = os.path.join(TMP_DIR, f'{comicid}_home.html')
        result = {'success': False, 'comicid': comicid,
                  'type': 0, 'is_del': False}
        try:
            if not url:
                res = self.download_comic_page(
                    str(comicid), tmp_file, self.cfg.get('cookie', None))
                if res:
                    page_data = self.parse_comic_page(tmp_file)
                    # https://18comic.org/javascript:void(0)
                    url = page_data['home_url']
                    if page_data.get('previous_comic', None):
                        logger.warning(f'{comicid} 是chapter')
                        result['is_del'] = True
                        return result

            if not url:
                raise ValueError('url为空')

            res = self.download_home_page(
                url, tmp_file, self.cfg.get('cookie', None))
            if res:
                home_data = self.parse_home_page(tmp_file)
                if home_data['page'] != 0:
                    if home_data['comicid'] != comicid:
                        logger.warning(f'{comicid} 不是漫画id，是章节id')
                        result['is_del'] = True
                        return result
                    home_data_to_db(self.db, home_data)
                    logger.info(f'{comicid} 下载主页数据成功。')
                    result['success'] = True
                    return result
                else:
                    logger.warning(f'{comicid} 解析主页数据出错')
                    return result
        except Exception as e:
            logger.error(f'{comicid} 下载主页数据出错。error:{e}')
            return result
        finally:
            if os.path.exists(tmp_file):
                os.unlink(tmp_file)

        return result

    def search(self, key: str, max: int = 0):
        """搜索，结果保存到数据库

        Args:
            key (str): _description_
            max (int, optional): _description_. Defaults to 0.
        """
        cookies = self.cfg.get("cookie", None)
        html_file = os.path.join(TMP_DIR, "search.html")
        page = 1
        max_page = 1

        logger.info(f'开始搜索[{key}]')
        with tqdm() as pbar:
            while True:
                res = self.download_search_page(
                    page=page, search=key, cookies=cookies, save_file=html_file)
                if res:
                    # 每次都更新最大页数
                    count = self.parse_search_total_page(html_file)
                    if count > max_page:
                        max_page = count
                    pbar.total = max_page
                    if max > 0 and max_page > max:
                        logger.info(f'搜索结果共{max_page}页, 只获取{max}页')
                        max_page = max
                    else:
                        if count == max_page:
                            logger.info(f'搜索结果共{max_page}页')

                    search_data = self.parse_search_page(
                        html_file, self.cfg.get('filter_tag', None))
                    search_data = list_deduplication(search_data)  # 去重
                    search_data_to_db(self.db, search_data)

                else:
                    logger.warning(f'获取搜索页面失败 [key]:{key}, [page]:{page}')

                pbar.update(1)

                if page >= max_page:
                    break
                page += 1

        if os.path.exists(html_file):
            os.unlink(html_file)
        logger.info(f'搜索[{key}]完成')

    def zip_comic(self, comicids: list) -> list:
        '''根据id列表打包漫画
        '''
        if not comicids:
            return []
        comicids = list(set(comicids))
        dirs = self.cfg.get('save_dir', [])
        zip_dirs = JMDirHandle.get_comics_dirs(comicids, dirs)
        if comicids:
            logger.warning(f'打包过程中，出现找到对应的文件 {" ".join(comicids)}')
        out_file = self.cfg.get('out_zip', 'jmcomic.zip')
        JMDirHandle.zip_dir(zip_dirs, out_file)

    def get_comic_dir(self, comicid: int, title: str) -> str:
        """根据id和标题返回文件夹

        Args:
            comicid (int): 漫画id
            title (str): 漫画标题(数据库的chapter_titile列)
        """
        save_dir = self.cfg.get('save_dir', os.path.abspath('.'))
        return JMDirHandle.create_comic_dir(comicid, title, save_dir)

    def check_search(self):
        """检查配置文件是否需要进行搜索
        搜索完后清空配置文件
        """
        search_dict = self.cfg.get('search', {})
        if search_dict:
            key = search_dict.get('key', '')
            max_page = search_dict.get('max_page', 0)
            if key:
                self.search(key, max_page)
                self.cfg['search'] = {"key": "", "max_page": 0}

    def download_comic_3(self):

        # 判断系统类型
        import platform
        os_name = platform.system()
        logger.info(f'当前系统是: {os_name}')

        # 启动ctrl+c信号监听
        is_interrupt = False

        def handler(sigint_obg: MySigint):
            print("接收到Ctrl+C信号")
            logger.info("接收到Ctrl+C信号")
            nonlocal is_interrupt
            is_interrupt = True
            sigint_obg.stop()
        mysigint = MySigint()
        res = mysigint.listening(handler, mysigint)
        if res:
            print('开始监听ctrl+c信号')
            logger.info('开始监听ctrl+c信号')
        else:
            print('监听ctrl+c信号失败')
            logger.warning('监听ctrl+c信号失败')

        # 数据库中未完成的漫画
        comics = query_static(self.db, 0)
        comic_index = 0
        logger.info(f'未完成的漫画数:{len(comics)}')

        # 循环下载
        print('Starting')
        logger.info('Starting')
        progress_log_time = self.cfg.get('progress_log', 60)
        start_time = time.time()
        tmp_time = start_time
        while not is_interrupt:
            while comics and self.queue_count() < 100 and comic_index < len(comics) and not is_interrupt:
                static = queue_comic_arr(
                    self.db, comics[comic_index], Comic.static)
                if static == 1:
                    comics.remove(comics[comic_index])
                else:
                    comicid = queue_comic_arr(
                        self.db, comics[comic_index], Comic.comicid)
                    if comicid:
                        try:
                            self.check_comic(comicid[0])
                        except Exception as e:
                            logger.error(
                                f'{comicid[0]} check_comic出错. {e}')
                comic_index += 1

            # self.check_comic(450324)

            self.task_to_pool()
            if len(self.pool.futures) == 0 and self.is_empty_queue():
                # 没有任务
                break

            # 等待处理，延时
            try:
                self.pool.wait(timeout=1, logger=logger)
            except TimeoutError:
                pass
            else:
                time.sleep(1)

            # 输出log
            if os_name != "Linux":
                clean_previous_line()
            print(
                f'完成数: { self.success_count} 线程任务数: {len(self.pool.futures)} 剩余任务数: {self.queue_count()}')
            end_time = time.time()
            if end_time - tmp_time >= progress_log_time:
                logger.info(
                    f'完成数: { self.success_count} 线程任务数: {len(self.pool.futures)} 剩余任务数: {self.queue_count()}')
                tmp_time = end_time

        print('Stoping')
        logger.info('Stoping')
        self.pool.wait(logger=logger)
        self.pool.close()
        
        logger.info(
            f'完成数: { self.success_count} 线程任务数: {len(self.pool.futures)} 剩余任务数: {self.queue_count()}')
        if self.queue_count() > 0:
            print(self.task_queue)
            logger.info(self.task_queue)
        end_time = time.time()
        execution_time = end_time - start_time
        hours = int(execution_time // 3600)
        execution_time %= 3600
        minutes = int(execution_time // 60)
        execution_time %= 60
        seconds = execution_time
        logger.info(f'总运行时间: {hours:02d}时{minutes:02d}分{seconds:02.2f}秒')

    def task_to_pool(self) -> bool:
        is_add = False
        if len(self.pool.futures) <= 5:
            for _ in range(10):
                task = self.pop_task_from_queue()
                if not task:
                    break
                is_add = True
                if task[0] == 0:
                    url = ''
                    comic = query_comic(self.db, task[1])
                    if comic:
                        url = comic.url
                    future = self.pool.add_task(
                        self.work_home_data, task[1], url)
                    if future:
                        future.add_done_callback(self.callback_download)
                elif task[0] == 1:
                    future = self.pool.add_task(self.work_page_data, task[1])
                    if future:
                        future.add_done_callback(self.callback_download)
                elif task[0] == 2:
                    comicimg = query_comicimg(self.db, task[1][0], task[1][1])
                    url = query_comicimg_arr(self.db, comicimg, ComicImg.url)
                    url = url[0]
                    img_path = self.get_img_path(task[1][0], url)
                    if not os.path.exists(img_path):
                        future = self.pool.add_task(
                            self.work_img, task[1][0], url, img_path)
                        if future:
                            future.add_done_callback(self.callback_download)
        return is_add

    def callback_download(self, future: Future):
        """回调函数，主页数据和页面数据线程callbakc
        判断漫画缺少哪些数据就补齐那部分的数据

        Args:
            future (Future): 线程对象
        """
        if future.done() and not future.cancelled():
            result = future.result()
            if result['success']:
                self.success_count += 1
                if result['type'] == 0:
                    self.check_comic(result['comicid'])
                elif result['type'] == 1 or result['type'] == 2:
                    chapter = query_chapter(self.db, result['comicid'])
                    if chapter:
                        comicid = query_chapter_comic(
                            self.db, chapter, Comic.comicid)
                        if comicid:
                            self.check_comic(comicid[0])
                        else:
                            raise Exception(f"章节 {result['comicid']} 没有搜索到主页")
            else:
                if result['type'] == 0:
                    self.remove_task_from_queue(0, result['comicid'])
                    if result.get('is_del', False):
                        comic = query_comic(self.db, result['comicid'])
                        if comic:
                            del_comic(self.db, comic)
                if result['type'] == 1:
                    self.remove_task_from_queue(1, result['comicid'])
                if result['type'] == 2:
                    # 重置任务，继续下载
                    self.reset_task_from_queue(
                        2, result['comicid'], result['page'])

    def check_comic(self, comicid: int) -> bool:
        comic = query_comic(self.db, comicid)
        if comic:
            is_done = self.check_homedata(comic)
            if not is_done:
                return

            chapters = query_comic_chapters(db, comic, Chapter)
            if chapters:
                for chapter in chapters:
                    is_done = self.check_chapter(chapter)
                    if is_done:
                        is_done = self.check_img(chapter)
                        if is_done:
                            chapter = modify_chapter(
                                self.db, chapter, static=1)

                statics = query_comic_chapters(db, comic, Chapter.static)
                statics = [static[0] == 1 for static in statics]
                if all(statics):
                    comic = modify_comic(self.db, comic, static=1)
                    logger.info(f'{comicid} 完成，共{len(chapters)}话')
                    return True
        return False

    def check_chapter(self, chapter: Chapter) -> bool:
        """判断是否添加页面任务

        Args:
            comic (Chapter): 章节对象
        """
        comicid, page, static = query_chapter_arr(
            self.db, chapter, Chapter.comicid, Chapter.page, Chapter.static)

        # 当漫画图片下载完成，static才置1
        # 由于网站问题，有的漫画是空白的，页数是零
        # 所以需要同时判断两个参数
        if page == 0 and static == 0:
            if self.chenck_queue(1, comicid):
                return False
            if self.download_content.get("chapter", True):
                self.add_task_to_queue(1, comicid)
        else:
            if self.remove_task_from_queue(1, comicid):
                logger.info(f'{comicid} 章节数据已经完成')
            return True

        return False

    def check_homedata(self, comic: Comic) -> bool:
        """判断是否添加主页任务

        Args:
            comic (Comic): 漫画对象
        """
        comicid, page = query_comic_arr(
            self.db, comic, Comic.comicid, Comic.page)
        if page == 0:
            if self.chenck_queue(0, comicid):
                return False
            if self.download_content.get("comic", True):
                self.add_task_to_queue(0, comicid)
        else:
            if self.remove_task_from_queue(0, comicid):
                logger.info(f'{comicid} 主页数据已经完成')
            return True

        return False

    def check_img(self, chapter: Chapter) -> bool:
        """判断是否下载页面数据

        Args:
            comic (Chapter): 章节对象
        """
        comicid = query_chapter_arr(self.db, chapter, Chapter.comicid)
        comicid = comicid[0]
        imgs = query_chapter_imgs(
            self.db, chapter, ComicImg.url, ComicImg.page)
        if not imgs:
            # 没有图片，就不用下载
            return True

        is_downloading = False
        is_add_task = False
        is_complet = True
        for url, page in imgs:
            img_path = self.get_img_path(comicid, url)
            if not img_path:
                # 获取路径出错，可能是路径太长，判断不了，直接退出算了
                logger.error(f'{comicid}获取图片路径出错，请检查目录名是否过长')
                break
            # 判断是否在任务中，如果有本地文件，表示已经下载完，对任务删除
            if self.chenck_queue(2, comicid, page):
                if os.path.exists(img_path):
                    self.remove_task_from_queue(2, comicid, page)
                else:
                    is_downloading = True
                    is_complet = False
            # 如果不在任务，也没有本地文件，就添加任务
            elif not os.path.exists(img_path):
                if self.download_content.get("img", True):
                    self.add_task_to_queue(2, comicid, page)
                    is_add_task = True
                is_complet = False

        if not is_downloading and is_add_task:
            # 没有下载中任务且进行添加任务，表示第一次下载
            # 这里主要用于发log
            logger.info(f'{comicid} 图片开始下载')

        return is_complet

    def check_comic_img_complet(self, chapter: Chapter) -> bool:
        """检查漫画是否完整
        通过文件数和页数比较

        Args:
            comic (Chapter): 章节对象

        Returns:
            bool: 文件数大于等于页数返回真
        """
        comicid, title, page = query_chapter_arr(
            self.db, chapter, Chapter.comicid, Chapter.title, Chapter.page)
        comic_dir = self.get_comic_dir(comicid, title)
        files = traversal_dir(comic_dir)
        return len(files) >= page

    def get_img_path(self, comicid: int, url: str) -> str:
        """根据漫画下载url生成漫画的图片路径

        Args:
            comicid (int): 漫画id
            url (str): 漫画下载url

        Returns:
            str: 图片路径
        """
        chapter = query_chapter(self.db, comicid)
        if not chapter:
            return None
        title = query_chapter_arr(self.db, chapter, Chapter.title)
        title = title[0]
        comic_dir = None
        try:
            comic_dir = self.get_comic_dir(comicid, title)
        except Exception as e:
            logger.error(e)
            comic = query_chapter_comic(self.db, chapter, Comic)
            if comic:
                comic = modify_comic(self.db, comic, static=5)
                comicid = query_comic_arr(self.db, comic, Comic.comicid)
                if comicid:
                    logger.info(f'{comicid[0]} 状态static设置为5')
        if not comic_dir:
            return None
        return JMDirHandle.get_img_path(url, comic_dir)

    def page_data_to_db(self, comicid: int, data: dict):
        """页面数据录入数据库
        通过判断home_url，来区分是都第一话，第一话写入comic表，非第一话写入chapter表

        Args:
            db (Session): 数据库
            comicid (int): 漫画id
            data (dict): 页面数据
        """
        # 更新页面数据
        chapter = query_chapter(self.db, int(comicid))
        if not chapter:
            chapter = add_chapter(
                self.db, models.Chapter(comicid=int(comicid)))
        chapter = modify_chapter(
            self.db, chapter, page=data['curr_page'], title=data['title'])
        chapterid = query_chapter_arr(self.db, chapter, Chapter.id)
        chapterid = chapterid[0]

        for url in data['urls']:
            page = int(url_to_filename(url).split('.')[0])
            img = query_comicimg_by_chapterid(self.db, chapterid, page)
            if not img:
                img = add_comicimg(self.db, ComicImg(url=url, page=page))
            modify_chapter(self.db, chapter, imgs=img)

    def chenck_queue(self, _type: int, comicid: int, page: int = 0) -> bool:
        with self.queue_lock:
            if _type == 0:
                return comicid in self.task_queue['comic']
            elif _type == 1:
                return comicid in self.task_queue['chapter']
            elif _type == 2:
                return (comicid, page) in self.task_queue['img']

    def add_task_to_queue(self, _type: int, comicid: int, page: int = 0):
        with self.queue_lock:
            if _type == 0:
                if not comicid in self.task_queue['comic']:
                    self.task_queue['comic'][comicid] = 0
            elif _type == 1:
                if not comicid in self.task_queue['chapter']:
                    self.task_queue['chapter'][comicid] = 0
            elif _type == 2:
                if not (comicid, page) in self.task_queue['img']:
                    self.task_queue['img'][(comicid, page)] = 0

    def remove_task_from_queue(self, _type: int, comicid: int, page: int = 0) -> bool:
        with self.queue_lock:
            if _type == 0:
                if comicid in self.task_queue['comic']:
                    del self.task_queue['comic'][comicid]
                    return True
            elif _type == 1:
                if comicid in self.task_queue['chapter']:
                    del self.task_queue['chapter'][comicid]
                    return True
            elif _type == 2:
                if (comicid, page) in self.task_queue['img']:
                    del self.task_queue['img'][(comicid, page)]
                    return True
        return False

    def pop_task_from_queue(self):
        for i in self.download_priority:
            res = self.priority_func[i[0]]()
            if res:
                return res
        return None

    def pop_comic_task_from_queue(self):
        for k, v in self.task_queue['comic'].items():
            if v == 0:
                self.task_queue['comic'][k] = 1
                return (0, k)
        return None

    def pop_chapter_task_from_queue(self):
        for k, v in self.task_queue['chapter'].items():
            if v == 0:
                self.task_queue['chapter'][k] = 1
                return (1, k)
        return None

    def pop_img_task_from_queue(self):
        for k, v in self.task_queue['img'].items():
            if v == 0:
                self.task_queue['img'][k] = 1
                return (2, k)
        return None

    def reset_task_from_queue(self, _type: int, comicid: int, page: int = 0):
        with self.queue_lock:
            if _type == 0:
                if comicid in self.task_queue['comic']:
                    self.task_queue['comic'][comicid] = 0
            elif _type == 1:
                if comicid in self.task_queue['chapter']:
                    self.task_queue['chapter'][comicid] = 0
            elif _type == 2:
                if (comicid, page) in self.task_queue['img']:
                    self.task_queue['img'][(comicid, page)] = 0

    def is_empty_queue(self) -> bool:
        with self.queue_lock:
            return not any((self.task_queue['comic'], self.task_queue['chapter'], self.task_queue['img']))

    def queue_count(self) -> int:
        with self.queue_lock:
            return len(self.task_queue['comic']) + len(self.task_queue['chapter']) + len(self.task_queue['img'])
        
    def check_1px_img(self):
        """检查1像素图片

        """
        res_list= []
        dir = self.cfg.get('save_dir', '')
        if os.path.isdir(dir):
            for sub_dir in os.listdir(dir):
                if os.path.isdir(os.path.join(dir,sub_dir)):
                    for file in os.listdir(os.path.join(dir,sub_dir)):
                        if os.path.isfile(os.path.join(dir,sub_dir,file)):
                            size = os.path.getsize(os.path.join(dir,sub_dir,file))
                            if size < 1024:
                                res_list.append(os.path.join(dir,sub_dir))
                                break
        
        if res_list:
            logger.info(f'{res_list}')


if __name__ == "__main__":
    pass
    jms = JMSpider()

    # 提取日志失败记录
    # print(log_filter_fail_id(r'data\jm_spider.log'))

    # 字符串提取comicid
    # jms.download_comic(extract_and_combine_numbers(''''''))

    # TODO 实现数据库删除
    # TODO 下载图片的，根据"image/jpg"格式判断图片类型