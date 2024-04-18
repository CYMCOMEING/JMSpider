import hashlib
import os
import re
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image
from tqdm import tqdm

from tools import (traversal_dir,
                   get_efficacious_filename,
                   url_to_filename,
                   get_subdir,
                   delete_dir_contents,
                   )


class JMImgHandle:

    @staticmethod
    def get_slices(comicid: str, pageid: str) -> int:
        """获取图片的切片数
        """
        md5 = hashlib.md5()
        n = ''.join((comicid, pageid))
        md5.update(n.encode())
        n = int(ord(md5.hexdigest()[-1]))

        # 注释部分是复现js的逻辑，后面已经进行简化
        # if (e > base64.b64decode("MjY4ODUw").decode()) and (e <= base64.b64decode("NDIxOTI1").decode()):
        #     n = n % 10
        # elif e >= str(base64.b64decode("NDIxOTI2")):
        #     n = n % 8

        if (comicid > '268850') and (comicid <= '421925'):
            n = n % 10
        elif comicid >= '421926':
            n = n % 8

        return (n+1)*2 if 0 <= n <= 9 else 10

    @staticmethod
    def img_slice_restore(img_file: str, out_file: str, slices: int) -> None:
        """根据图片切片数进行还原
        """

        img = Image.open(img_file)

        # 获取图片的宽度和高度
        width, height = img.size

        # 创建一个空白图片，大小与原图一致，背景色为白色
        new_img = Image.new('RGB', (width, height), 'white')

        # 切片高度
        slice_h = int(height / slices)
        slice_other = height % slices
        for i in range(slices):
            # 旧图起始y坐标
            in_img_y = height - slice_h * (i + 1) - slice_other

            # 旧图结束y坐标
            # 新图起始y坐标
            if i == 0:
                in_img_endy = height
                out_img_y = 0
            else:
                in_img_endy = in_img_y + slice_h
                out_img_y = slice_h * i + slice_other

            # crop() 4个参数分别起始坐标和结束坐标
            old_img = img.crop((0, in_img_y, width, in_img_endy))
            new_img.paste(old_img, (0, out_img_y))

        new_img.save(out_file)

    def restore_img(comicid: str, pageid: str, img_file: str, out_file: str = None):
        slices = JMImgHandle.get_slices(comicid, pageid)
        if not out_file:
            out_file = img_file
        JMImgHandle.img_slice_restore(img_file, out_file, slices)

    @classmethod
    def restore_imgs(cls, comicid: str, dir: str, out_dir: str = None):
        """把指定目录下的图片进行还原，输出到指定位置
        """
        if not out_dir:
            out_dir = os.path.join(dir, 'outfile')

        if not os.path.exists(out_dir):
            os.mkdir(out_dir)

        for i in tqdm(traversal_dir(dir)):
            pageid = os.path.basename(i).split('.')[0]
            save_path = os.path.join(out_dir, os.path.basename(i))
            cls.restore_img(comicid, pageid, i, save_path)


class JMDirHandle:
    """管理禁漫下载的漫画

    每部漫画的目录以 comicid-漫画标题 格式存放
    内容每张以 00001.jpg 格式命名
    """

    @staticmethod
    def get_comics_dirs(comicids: list, dirs: list) -> list:
        """获取comicids的目录，当comicid存在dirs中，就会被返回

        Args:
            comicids (list): 漫画id字符串列表
            dirs (list): 要搜索的目录

        Returns:
            list: 返回路径列表
        """
        ret_list = []
        if not (comicids and dirs):
            return ret_list
        for dir in dirs:
            for file in os.listdir(dir):
                if os.path.isdir(os.path.join(dir, file)):
                    id = file.split('-')[0]
                    if id in comicids:
                        ret_list.append(os.path.abspath(
                            os.path.join(dir, file)))
                        comicids.remove(id)
        return ret_list

    @staticmethod
    def get_dir_comicid(dir: str) -> list:
        """获取目录下所有的comicid
        """
        ids = []
        if os.path.exists(dir):
            for name in os.listdir(dir):
                try:
                    if os.path.isdir(os.path.join(dir, name)):
                        s = name.split('-')
                        if len(s) > 1:
                            ids.append(s[0])
                except:
                    pass
        return ids

    @staticmethod
    def get_dirs_comicid(dirs: list) -> list:
        """获取多个目录下所有的comicid
        """
        ids = []
        for i in dirs:
            ids.extend(JMDirHandle.get_dir_comicid(i))
        return ids

    @staticmethod
    def dir_to_comicid(dir: str) -> str:
        """从目录中提取comicid

        Args:
            dir (str): 目录

        Returns:
            str: comicid
        """
        name = os.path.basename(dir)
        comp = re.compile('(\d+)-')
        res = re.findall(comp, name)
        if res:
            return res[0]
        return None

    @staticmethod
    def jpg_to_page(jpg_file: str) -> int:
        """从漫画图片名中提取页数

        Args:
            jpg_file (str): 漫画图片名

        Returns:
            int: 页数
        """
        name = os.path.basename(jpg_file)
        comp = re.compile('(\d+).jpg')
        res = re.findall(comp, name)
        if res:
            return int(res[0])
        return None

    # @staticmethod
    # def load_comicid_from_file(file: str):
    #     """读取文件中的comicid
    #     fliter_file文件中的内容每个comicid用空格隔开，支持换行
    #     """
    #     ids = []
    #     with open(file, 'r', encoding='utf-8') as f:
    #         data = f.readline()
    #         while data:
    #             data = data.rstrip('\n')
    #             for i in data.split(' '):
    #                 ids.add(i)
    #             data = f.readline()

    #     if not ids:
    #         return None

    @staticmethod
    def comicid_fliter(ids: set):
        """协程，判断id是否在ids中

        调用该函数返回一个生成器，先执行next()，然后再循环用send()发送
        """
        if not ids:
            return None

        comicid = ''
        while True:
            comicid = yield comicid in ids

    @staticmethod
    def create_comic_dir(comicid: int, title: str, save_dir: str) -> str:
        """根据参数创建comic目录
        """
        dir = os.path.join(save_dir,
                           get_efficacious_filename('-'.join((str(comicid), title)))
                           )
        # os.makedirs(dir, exist_ok=True)
        try:
            if not os.path.exists(dir):
                os.mkdir(dir)
        except Exception as e:
            print(e)
        return dir

    def get_img_path(url, save_dir: str) -> str:
        """根据图片url参数生成文件路径
        """
        img_path = '{}.jpg'.format(os.path.splitext(url_to_filename(url))[0])
        return os.path.join(save_dir, img_path)

    @staticmethod
    def comic_clean(dir):
        """清空目录下所有漫画，但不删除目录

        注意：会误删除其他文件，需要保证没有其他文件或目录
        """
        dirs = get_subdir(dir)
        for i in dirs:
            delete_dir_contents(i)

    # @staticmethod
    # def del_outfile_img(dir: str):
    #     """删除目录下所有漫画outfile下的文件
    #     """
    #     dirs = get_subdir(dir)
    #     for directory in dirs:
    #         outfile_dir = os.path.join(directory, 'outfile')
    #         try:
    #             shutil.rmtree(outfile_dir)
    #         except:
    #             pass

    # @staticmethod
    # def outfile_replace_source(dir: str):
    #     """把comic的源文件替换成outfile的文件
    #     """
    #     outfile_dir = os.path.join(dir, 'outfile')
    #     if not (os.path.exists(outfile_dir) and os.path.isdir(outfile_dir)):
    #         return

    #     files = os.listdir(outfile_dir)
    #     if not files:  # outfile下面没有文件千万别删源文件
    #         return

    #     for file in os.listdir(dir):
    #         path = os.path.join(dir, file)
    #         if os.path.isfile(path):
    #             os.unlink(path)
    #     for file in files:
    #         path = os.path.join(outfile_dir, file)
    #         shutil.move(path, dir)

    #     shutil.rmtree(outfile_dir)

    @staticmethod
    def zip_dir(dirs: list, out_file: str):
        """打包漫画
        """
        if not dirs:
            return

        with ZipFile(out_file, 'w', ZIP_DEFLATED) as myzip:
            for dir in dirs:
                if not os.path.isdir(dir):
                    continue
                write_dir = os.path.basename(dir)
                myzip.mkdir(write_dir)
                for file in os.listdir(dir):
                    path = os.path.join(dir, file)
                    if os.path.isfile(path):
                        myzip.write(path, os.path.join(write_dir, file))

    @staticmethod
    def simple_check_comic(comic_dir: str) -> bool:
        """简单检漫画文件是否完整
        漫画图片是以00001.jpg格式命名，通过找出最大文件名，
        检查文件数量是否等于文件名来判断漫画是否完整。

        存在问题：如果缺失的是漫画未尾文件就没办法检测出来。

        Args:
            comic_dir (str): 漫画目录

        Returns:
            bool: 不缺失返回True
        """
        files = traversal_dir(comic_dir)
        if files:
            files.sort()  # 字符串小到大
            # print(*files,sep='\n')
            max = JMDirHandle.jpg_to_page(files[-1])
            if max > len(files):
                return False
        return True


def extract_and_combine_numbers(input_strings: str):
    """提取字符串所有数字，组合成新的字符串
    """
    res = []
    for i in input_strings.split('\n'):
        numbers = re.findall(r'\d+', i)
        number = ''.join(numbers)
        if number:
            res.append(number)
    return res


def log_filter_fail_id(log_file: str):
    '''从log文件中提取下载图片失败的id
    '''
    ret_list = set()
    comp1 = re.compile(r'(\d+) 下载图片失败')
    # comp2 = re.compile(r'下载网页失败: (\d+)')

    with open(log_file, 'r', encoding='utf-8') as f:
        s = f.read()
        res = re.findall(comp1, s)
        for i in res:
            ret_list.add(i)
        # res = re.findall(comp2, s)
        # for i in res:
        #     ret_list.add(i)

    return ret_list


if __name__ == "__main__":
    pass
    dir = r'D:\禁漫天堂\data\禁漫天堂\未整理\7347-母さんじゃなきゃダメなんだっ 2'
    print(JMDirHandle.simple_check_comic(dir))
    # jpg = r'D:\禁漫天堂\data\禁漫天堂\未整理\16576-[LINDA] W-HIP-asdfasdf\00001.jpg'
    # print(JMDirHandle.jpg_to_page(jpg))
