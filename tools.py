import os
import functools
import re
from urllib.parse import urlparse
import shutil
from logging import Logger
import time


def retry(times: int = 3, sleep: int = 0, logger: Logger = None):
    """装饰器，实现重试功能

    根据返回值判断是否重试
    """
    def wrapper1(func):
        @functools.wraps(func)
        def wrapper2(*args, **kwargs):
            count = 0
            while count < times:
                try:
                    res = func(*args, **kwargs)
                except Exception as e:
                    res = None
                    if logger:
                        args_s = ",".join(map(str, args))
                        kwargs_s = ",".join(
                            f"{key}={value}" for key, value in kwargs.items())
                        logger.info(
                            f'[function]:{func.__name__},[args]:{args_s},[kwargs]:{kwargs_s},[Error]:{e}')
                    if sleep:
                        time.sleep(sleep)
                if res:
                    break
                count += 1
            return res
        return wrapper2
    return wrapper1


def count_sleep(func):
    '''装饰器，统计函数调用次数，到达次数会进行休眠数秒

    累计5次下载,休眠1秒
    '''
    count = 0
    MAX = 5
    SLEEP = 1

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        nonlocal count, MAX

        if count >= MAX:
            time.sleep(SLEEP)
            count = 0

        res = func(*args, **kwargs)
        count += 1
        return res
    return wrapper


def get_efficacious_filename(filename: str) -> str:
    """把windows中不能创建文件或目录的特殊符号转成中文符号

    中文双引号有闭合的，先不管，都用一种
    """
    char_dict = {'\\': '、', '/': '、', ':': '：', '*': '',
                 '?': '？', '"': '“', '<': '《', '>': '》', '|': '丨'}
    for i, j in char_dict.items():
        filename = re.sub(re.escape(i), j, filename)
    return filename


def url_to_filename(url):
    """从url获取下载的文件名
    """
    path = urlparse(url).path
    filename = path.split("/")[-1]
    filename = get_efficacious_filename(filename)
    if not verify_filename(filename):
        raise Exception(f'文件名、目录名或卷标语法不正确。:{filename}')
    return filename


def verify_filename(filename: str):
    """检验文件名是否合法
    """
    try:
        os.path.basename(filename)
    except:
        return False
    return True


def traversal_dir(directory):
    """遍历目录下的文件
    """
    files = os.listdir(directory)
    return [os.path.join(directory, f) for f in files if os.path.isfile(os.path.join(directory, f))]


def get_subdir(dir: str) -> list:
    """获取目录下所有的文件夹
    """
    subdirectories = []
    if os.path.exists(dir):
        for d in os.listdir(dir):
            path = os.path.join(dir, d)
            if os.path.isdir(path):
                subdirectories.append(os.path.abspath(path))
    return subdirectories


def delete_dir_contents(directory: str) -> None:
    """删除目录下所有内容

    注意：shutil.rmtree会连本目录都会删除
    """
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except:
            pass
