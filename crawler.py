from io import BytesIO

import requests
from requests import Response
from curl_cffi import requests as cffi_requests
from PIL import Image, UnidentifiedImageError


class RequestError(Exception):
    """ 请求错误 """
    pass

class Crawler:
    def __init__(self,
                 url:str,
                 cookies:dict=None,
                 headers:dict=None,
                 params:dict=None,
                 ) -> None:
        self.url = url
        self.cookies=cookies
        self.headers=headers
        self.params=params

    def get(self) -> Response:
        response = requests.get(self.url, 
                                params=self.params, 
                                cookies=self.cookies, 
                                headers=self.headers,
                                )
        if response.status_code == 200:
            return response
        return None


class HtmlCrawler(Crawler):

    def get(self, save_file:str) -> bool:
        response = super().get()
        if response:
            with open(save_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
                return True
        return False
    

class WebpCrawler(Crawler):

    def get(self, save_file:str) -> bool:
        response = super().get()
        if response and (response.headers.get('Content-Type', '') == r'image/webp'):
            # 图片是webp格式，转jpg
            try:
                with Image.open(BytesIO(response.content)) as img:
                    jpg_img = img.convert('RGB')
                    jpg_img.save(save_file)
                    return True
            except UnidentifiedImageError:
                # 请求成功，但是数数据有问题，就创建一个像素的图片
                img = Image.new('RGB', (1, 1), color = (255, 255, 255))
                img.save(save_file)
                return True
        return False

class TSLCrawler:

    def __init__(self,
                 url:str,
                 cookies:dict=None,
                 headers:dict=None,
                 params:dict=None,
                 proxies:dict=None,
                 ) -> None:
        self.url = url
        self.cookies=cookies
        self.headers=headers
        self.params=params
        self.proxies=proxies

    def get(self) -> Response:
        response = cffi_requests.get(self.url, 
                                params=self.params, 
                                cookies=self.cookies, 
                                headers=self.headers,
                                proxies=self.proxies,
                                timeout=60,
                                impersonate=cffi_requests.BrowserType.chrome
                                )
        if response.status_code == 200:
            return response
        return None
    
class HtmlTSLCrawler(TSLCrawler):
    def get(self, save_file:str) -> bool:
        response = super().get()
        if response:
            with open(save_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
                return True
        return False