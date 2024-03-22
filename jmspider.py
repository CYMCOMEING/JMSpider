import os
from datetime import date
import time
import signal

from lxml import etree
from tqdm import tqdm

from crawler import HtmlCrawler, WebpCrawler
from tools import retry, count_sleep, get_subdir
from playwright_tool import login
from jmtools import JMImgHandle, JMDirHandle, extract_and_combine_numbers, log_filter_fail_id
from jmconfig import cfg
from jmlogger import logger


# TODO 中断在下载图片处中断
# TODO 把过滤id作为全局，不一定
# TODO 线程池

class JMSpider:
    """禁漫爬虫

    通过禁漫的漫画id进行爬取，
    内容保存到以 "id-漫画标题" 格式的目录中
    """

    _transform_id = 220981  # 从这个id开始，图片都是乱序的，怎么得来的？一个个顺序排查的
    _headers = {'user-agent': 'PostmanRuntime/7.34.0', }

    def __init__(self) -> None:
        self.cfg = cfg

    def update_cookies(self) -> bool:
        """自动登录，获取cookie写入配置中
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

        暂时不知道cookie有效期，现在设定每天都登录
        """
        return not (str(date.today()) == self.cfg.get('cookie_update', ''))

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_comic_page(cls, comicid: str, save_file: str, cookies: dict = None, page: int = None) -> bool:
        """下载漫画页面
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

    @staticmethod
    def parse_comic_page(html_file: str) -> dict:
        """解析漫画页面，返回数据

        return: urls,title,max_page,next_comic
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
        max_page = root_element.xpath(
            '//div[@class="hidden-xs"]/ul[@class="pagination"]/li[last()-1]/a/text()')
        if max_page:
            max_page = int(max_page[0])
            ret_data['max_page'] = max_page
        else:
            ret_data['max_page'] = 1

        return ret_data

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_comic_img(cls, url: str, save_file: str) -> bool:
        """下载图片
        """
        wc = WebpCrawler(url, headers=cls._headers)
        return wc.get(save_file)

    @classmethod
    @retry(sleep=1)
    @count_sleep
    def download_search_page(cls, page: int, search: str, save_file: str, cookies: dict = None) -> bool:
        """下载搜索页面
        """

        if not cookies:
            cookies = {}
        cookies['_gali'] = 'wrapper'

        '''
        参数
        排序 o: tf 点赞最多，mp 图片最多，mv 阅读最多， mr 最新的(默认)
        发布时间 t: t 今天，w 这周，m 本月，a 全部(默认)
        '''
        params = {
            'search_query': search,
            'page': '{}'.format(page),
        }

        hc = HtmlCrawler(url='https://18comic.org/search/photos',
                         params=params,
                         headers=cls._headers,
                         cookies=cookies
                         )
        return hc.get(save_file)

    @staticmethod
    def parse_search_page(html_file: str, filter: list = None) -> list:
        """搜索结果页面提取comicid
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
            a_href = i.xpath('div/a/@href')
            if not a_href:
                continue
            comicid = a_href[0].split('/')[-2]

            # 判断是否过滤
            if filter:
                a_tags = i.xpath('div/div[2]//a/text()')
                if set(filter) & set(a_tags):
                    continue
            res_list.append(comicid)

        return res_list

    @staticmethod
    def parse_search_total_page(html_file: str) -> int:
        """搜索页面获取总页数
        """
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()
        root_element = etree.HTML(html)
        page = root_element.xpath('//ul[@class="pagination"]/li[8]/a/text()')
        if page:
            return int(page[0])
        return 1

    def stop_signal_handler(self, signum, frame):
        """更改停止标志
        """
        logger.info('接收到 Ctrl + C 信号')
        self.stop_flag = True

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
                logger.info(f'下载完成: {download_id}, 花费时间: {end_time - start_time:.2f}秒')

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
        """搜索，把结果保存到文件中
        """
        cookies = self.cfg.get("cookie", None)
        html_file = "search.html"
        page = 1
        max_page = 1

        logger.info(f'开始搜索[{key}]')
        ids = []
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

                    ids.extend(self.parse_search_page(
                        html_file, self.cfg.get('filter_tag', None)))
                else:
                    logger.info(f'获取搜索页面失败 [key]:{key}, [page]:{page}')

                pbar.update(1)

                if page >= max_page:
                    break
                page += 1

            if ids:
                self.save_idfile(ids)

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
