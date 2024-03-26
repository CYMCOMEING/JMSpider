from sqlalchemy.orm import Session
from threading import Lock
import functools

from database import models
from database.database import engine
from tools import get_efficacious_filename

models.Base.metadata.create_all(bind=engine)  # 创建表
db_lock = Lock()
# TODO 用装饰器加锁

def lock(lock:Lock):
    def wrapper1(func):
        @functools.wraps(func)
        def wrapper2(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return wrapper2
    return wrapper1

@lock(db_lock)
def add_comic(db: Session, comic: models.Comic, commit=True) -> models.Comic:
    db.add(comic)
    if commit:
        db.commit()
        db.refresh(comic)
    return comic

@lock(db_lock)
def query_comic(db: Session, comic_id: str) -> models.Comic | None:
    return db.query(models.Comic).filter(models.Comic.comicid == comic_id).first()

@lock(db_lock)
def query_static(db: Session, static: int) -> list[models.Comic] | None:
    return db.query(models.Comic).filter(models.Comic.static == static).all()

def home_data_to_db(db: Session, data: dict) -> bool:
    """漫画详情页数据入数据库

    Args:
        db (Session): 数据库
        data (dict): 漫画主页数据

    Returns:
        models.Comic | None: 返回入库后的对象
    """

    # 主键，没有就退出
    comicid = data.get('comicid', None)
    if not comicid:
        return False
    
    # 判断是否有多章节，每个章节算一个条记录
    update_ids = []
    next = data.get('next', None)
    if next:
        update_ids.extend(next)
    else:
        update_ids.append(comicid)
    
    for id in update_ids:
        res = query_comic(db, id)
        if res:
            comic = res
        else:
            comic = models.Comic(comicid=id)

        comic.static = 0
        comic.url = data.get('url', '')
        comic.title = data.get('title', '')
        comic.description = data.get('description', '')
        comic.page = data.get('page', 0)
        tags = data.get('tags', None)
        if tags:
            comic.tags = ' '.join(tags)
        author = data.get('author', None)
        if author:
            comic.author = ' '.join(author)
        next = data.get('next', None)
        if next:
            comic.next = ' '.join(next)
        
        add_comic(db, comic)

    return True


def search_data_to_db(db: Session, data: list) -> None:
    """搜索页面解析的数据入数据库

    Args:
        db (Session): 数据库
        data (list): 搜索数据，格式[[id, url],[id, url],...,[id, url]]
    """
    with db.begin():
        for item in data:
            res = query_comic(db, item[0])
            if res:
                comic = res
            else:
                comic = models.Comic(comicid=item[0])

            if not comic.url:
                comic.url = item[1]
                db.add(comic)

def page_data_to_db(db: Session, comicid:str, data: dict) -> models.Column:
    res = query_comic(db, comicid)
    if res:
        comic = res
    else:
        comic = models.Comic(comicid=comicid)

    comic.curr_page = data['curr_page']
    comic.chapter_titile = data['title']
    comic.url = data['home_url']

    return add_comic(db, comic)