from sqlalchemy.orm import Session
from threading import Lock
import functools

from database import models
from database.database import engine
from tools import get_efficacious_filename

models.Base.metadata.create_all(bind=engine)  # 创建表
db_lock = Lock()


def lock(lock: Lock):
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
def add_comics(db: Session, comics: list[models.Comic], commit=True):
    db.add_all(comics)
    if commit:
        db.commit()


@lock(db_lock)
def query_comic(db: Session, comic_id: int) -> models.Comic | None:
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

    comic = query_comic(db, int(data.get('comicid', 0)))
    if not comic:
        comic = models.Comic(comicid=int(id))

    comic.static = 0
    comic.url = data.get('url', '')
    comic.title = data.get('title', '')
    comic.description = data.get('description', '')
    comic.page = data.get('page', 0)
    author = data.get('author', None)
    if author:
        comic.author = ' '.join(author)

    tags = data.get('tags', [])
    for tag in tags:
        res_tag = query_tag(db, tag)
        if not res_tag:
            res_tag = models.Tag(text=tag)
            add_tag(db, res_tag)
        comic.tags.append(res_tag)

    nexts = data.get('next', [])
    for next in nexts:
        next_comic = query_chapter(int(next))
        if not next_comic:
            next_comic = models.Chapter(comicid=int(next))
        # next_comic.main_comic = comic.id
        next_comic.chapter_num = nexts.index(next) + 1
        add_chapter(db, next_comic)

        comic.chapters.append(next_comic)

    add_comic(db, comic)

    return True


def search_data_to_db(db: Session, data: list) -> None:
    """搜索页面解析的数据入数据库

    Args:
        db (Session): 数据库
        data (list): 搜索数据，格式[[id, url],[id, url],...,[id, url]]
    """
    comics = []
    for item in data:
        res = query_comic(db, int(item[0]))
        if res:
            comic = res
        else:
            comic = models.Comic(comicid=int(item[0]))

        if not comic.url:
            comic.url = item[1]
            comics.append(comic)
    if comics:
        add_comics(db, comics)


def page_data_to_db(db: Session, comicid: str, data: dict):
    """页面数据录入数据库
    通过判断home_url，来区分是都第一话，第一话写入comic表，非第一话写入chapter表

    Args:
        db (Session): 数据库
        comicid (str): 漫画id
        data (dict): 页面数据
    """

    if comicid in data['home_url']:
        res = query_comic(db, int(comicid))
    else:
        res = query_chapter(db, int(comicid))

    if not res:
        if comicid in data['home_url']:
            comic = models.Comic(comicid=int(comicid))
            comic.curr_page = data['curr_page']
            comic.chapter_titile = data['title']
            comic.url = data['home_url']
            add_comic(db, comic)
        else:
            chapter = models.Chapter(comicid=int(comicid))
            chapter.curr_page = data['curr_page']
            chapter.chapter_titile = data['title']
            add_chapter(chapter)


@lock(db_lock)
def query(db: Session):
    return db.query(models.Comic).all()


@lock(db_lock)
def query_tag(db: Session, tag: str) -> models.Tag:
    return db.query(models.Tag).filter(models.Tag.text == tag).first()


@lock(db_lock)
def add_tag(db: Session, tag: models.Tag) -> models.Tag:
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@lock(db_lock)
def add_chapter(db: Session, chapter: models.Chapter) -> models.Chapter:
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@lock(db_lock)
def query_chapters(db: Session) -> list[models.Chapter] | None:
    return db.query(models.Chapter).all()


@lock(db_lock)
def query_chapter(db: Session, comicid: int) -> models.Chapter | None:
    return db.query(models.Chapter).filter(models.Chapter.comicid == comicid).first()
