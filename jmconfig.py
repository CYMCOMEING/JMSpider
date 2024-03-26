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
    "save_dir": os.path.abspath('.'),
    "download_file": "",
    "out_zip": "",
    "filter_dir": [],
    "blacklist": "",
    "username": "",
    "password": "",
    "cookie": {
                "AVS": ""
    },
    "cookie_update": "",
    "proxies": None,
    "redownload":[],
    "redownloading":[]
}

# cfg = MyConfig().load(JSON_PATH)
# if not cfg:
#     cfg = deepcopy(DEFUALT_DATA)

# def save_config(json_data: object):
#     MyConfig.dump(json_data, JSON_PATH, DEFUALT_DATA)
class MyConfig(dict):
    def __init__(self, config_path: str) -> None:
        self.fio = None
        self.fio = open(config_path, 'a+', encoding='utf-8')
        self.fio.seek(0)  # 追加方式打开，指针会在最后
        data = self.fio.read()
        if not data: # 文件内容为空时，json会报错
            data = "{}"
        json_data = json.loads(data)
        self.update(json_data)

    def save(self):
        self.fio.seek(0)
        json.dump(self, self.fio, ensure_ascii=False, indent=4)
        self.fio.flush()  # 将缓存刷新到磁盘
        self.fio.truncate() # 清空指针位置后面的内容，会直接写磁盘

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

def config_init(file:str, defualt = None) -> dict:
    conf = MyConfig(file)
    if defualt and (not conf):
        conf.update(defualt)
    return conf

cfg = config_init(JSON_PATH, DEFUALT_DATA)