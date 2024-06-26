from copy import deepcopy
import os
import json

# class MyConfig:
#     @staticmethod
#     def load(json_path: str) -> dict:
#         if os.path.isfile(json_path):
#             with open(json_path, 'r', encoding='utf-8') as f:
#                 return json.load(f)
#         return {}

#     @staticmethod
#     def dump(json_object: object, json_path: str, default:dict=None):
#         with open(json_path, 'w', encoding='utf-8') as f:
#             json.dump(json_object, f, default=default, ensure_ascii=False)


json_dir = os.path.join(os.path.abspath('.'), 'data')
os.makedirs(json_dir, exist_ok=True)
# if not os.path.exists(json_dir):
#     os.mkdir(json_dir)

JSON_PATH = os.path.join(json_dir, 'config.json')
DEFUALT_DATA = {
    "progress_log": 60,
    "download_content":{
        "comic":True,
        "chapter":True,
        "img":True
    },
    "download_priority":{
        "comic":0,
        "chapter":1,
        "img":2
    },
    "search": {
        "key": "",
        "max_page": 0
    },
    "filter_tag": [
        "yaoi",
        "cosplay",
        "3D",
        "韓漫",
        "韩漫",
        "國漫",
        "国漫",
        "非H",
        "菲H",
        "日文",
        "英文",
        "連載中",
        "连载中",
        "女性向",
        "毛絨絨",
        "毛绒绒",
        "CG",
        "ゲームCG",
        "AI繪圖",
        "PIXIV",
        "動圖",
        "动图"
    ],
    "save_dir": "",
    "out_zip": "",
    "username": "",
    "password": "",
    "cookie": {
        "AVS": "ujihs07clue9e3usbp2uq08rjo",
        "_gali": "wrapper"
    },
    "cookie_update": "",
    "proxies": {}
}


class MyConfig(dict):
    def __init__(self, config_path: str) -> None:
        self.fio = None

        # 文件不存在则创建文件
        if not os.path.exists(config_path):
            with open(config_path, 'w', encoding='utf-8'):
                pass
        self.fio = open(config_path, 'r+', encoding='utf-8') # 不能用a+，a+只能追加内容，不能在指定位置修改内容
        data = self.fio.read()
        if not data:  # 文件内容为空时，json会报错
            data = "{}"
        json_data = json.loads(data)
        self.update(json_data)

    def save(self):
        self.fio.seek(0)
        json.dump(self, self.fio ,ensure_ascii=False, indent=4)
        self.fio.flush()  # 将缓存刷新到磁盘
        self.fio.truncate()  # 清空指针位置后面的内容，会直接写磁盘

    def close(self):
        if self.fio:
            self.fio.close()

    def __del__(self):
        self.close()

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __setitem__(self, key: object, value: object) -> None:
        super().__setitem__(key, value)
        self.save()

    def get(self, key, default=None):
        return super().get(key, default)


def config_init(file: str, defualt=None) -> dict:
    conf = MyConfig(file)
    if defualt and (not conf):
        conf.update(defualt)
    return conf


cfg = config_init(JSON_PATH, DEFUALT_DATA)
