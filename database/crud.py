from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from threading import Lock
import functools

from database import models
from database.database import engine

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
def refresh(db: Session, obj):
    db.refresh(obj)


'''Comic
'''


@lock(db_lock)
def add_comic(db: Session, comic: models.Comic, commit=True) -> models.Comic:
    db.add(comic)
    if commit:
        db.commit()
        db.refresh(comic)
    return comic


@lock(db_lock)
def query_comic(db: Session, comicid: int) -> models.Comic | None:
    return db.query(models.Comic).filter(models.Comic.comicid == comicid).first()


@lock(db_lock)
def query_comics(db: Session) -> list[models.Comic] | None:
    return db.query(models.Comic).all()


@lock(db_lock)
def query_static(db: Session, static: int) -> list[models.Comic] | None:
    return db.query(models.Comic).filter(models.Comic.static == static).all()


@lock(db_lock)
def del_comic(db: Session, comic: models.Comic):
    db.delete(comic)
    db.commit()

@lock(db_lock)
def queue_comic_arr(db: Session, comic:models.Comic, *args) -> tuple:
    return db.query(*args).filter(models.Comic.id == comic.id).first()


@lock(db_lock)
def modify_comic(db: Session, comic: models.Comic, **kwargs) -> models.Comic:
    db.refresh(comic)
    if 'chapters' in kwargs:
        if kwargs['chapters'] not in comic.chapters:
            comic.chapters.append(kwargs['chapters'])
    if 'url' in kwargs:
        comic.url = kwargs['url']
    if 'static' in kwargs:
        comic.static = kwargs['static']
    if 'title' in kwargs:
        comic.title = kwargs['title']
    if 'description' in kwargs:
        comic.description = kwargs['description']
    if 'page' in kwargs:
        comic.page = kwargs['page']
    if 'author' in kwargs:
        comic.author = kwargs['author']
    if 'tags' in kwargs:
        tags = set(kwargs['tags'])
        for tag in tags:
            res_tag = db.query(models.Tag).filter(
                models.Tag.text == tag).first()
            if not res_tag:
                res_tag = models.Tag(text=tag)
                db.add(res_tag)
            if res_tag not in comic.tags:
                comic.tags.append(res_tag)
    db.commit()
    db.refresh(comic)
    return comic

@lock(db_lock)
def query_comic_chapters(db: Session, comic:models.Comic, *args) -> tuple:
    return db.query(*args).filter(models.Comic.id == comic.id).join(models.Comic, models.Comic.id == models.Chapter.main_comic).all()

@lock(db_lock)
def query_comic_arr(db: Session, comic:models.Comic, *args) -> tuple:
    return db.query(*args).filter(models.Comic.id == comic.id).first()




'''
Tag
'''


@lock(db_lock)
def query_tag(db: Session, tag: str) -> models.Tag:
    return db.query(models.Tag).filter(models.Tag.text == tag).first()


@lock(db_lock)
def add_tag(db: Session, tag: models.Tag) -> models.Tag:
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


'''
Chapter
'''


@lock(db_lock)
def add_chapter(db: Session, chapter: models.Chapter) -> models.Chapter:
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter

@lock(db_lock)
def modify_chapter(db: Session, chapter: models.Chapter, **kwargs) -> models.Chapter:
    db.refresh(chapter)
    if 'static' in kwargs:
        chapter.static = kwargs['static']
    if 'imgs' in kwargs:
        if kwargs['imgs'] not in chapter.imgs:
            chapter.imgs.append(kwargs['imgs'])
    if 'chapter_num' in kwargs:
        chapter.chapter_num = kwargs['chapter_num']
    if 'title' in kwargs:
        chapter.title = kwargs['title']
    if 'page' in kwargs:
        chapter.page = kwargs['page']
    db.commit()
    db.refresh(chapter)
    return chapter


@lock(db_lock)
def query_chapters(db: Session) -> list[models.Chapter] | None:
    return db.query(models.Chapter).all()


@lock(db_lock)
def query_chapter(db: Session, comicid: int) -> models.Chapter | None:
    return db.query(models.Chapter).filter(models.Chapter.comicid == comicid).first()


@lock(db_lock)
def query_chapters_static(db: Session, static: int) -> list[models.Chapter] | None:
    return db.query(models.Chapter).filter(models.Chapter.static == static).all()

@lock(db_lock)
def query_chapter_arr(db: Session, chapter:models.Chapter, *args) -> tuple:
    return db.query(*args).filter(models.Chapter.id == chapter.id).first()

@lock(db_lock)
def query_chapter_imgs(db: Session, chapter:models.Chapter, *args) -> tuple:
    return db.query(*args).filter(models.Chapter.comicid == chapter.comicid).join(models.Chapter, models.Chapter.id == models.ComicImg.chapterid).all()

@lock(db_lock)
def query_chapter_comic(db: Session, chapter:models.Chapter, *args) -> tuple:
    return db.query(*args).filter(models.Chapter.comicid == chapter.comicid).join(models.Chapter, models.Chapter.main_comic == models.Comic.id).first()

'''
ComicImg
'''
@lock(db_lock)
def query_comicimg(db: Session, comicid: int, page: int) -> models.ComicImg | None:
    chapter = db.query(models.Chapter).filter(
        models.Chapter.comicid == comicid).first()
    if not chapter:
        return None
    return db.query(models.ComicImg) \
        .filter(
            and_(
                models.ComicImg.chapterid == chapter.id,
                models.ComicImg.page == page
            )
    ).first()


@lock(db_lock)
def query_comicimg_by_chapterid(db: Session, chapterid: int, page: int) -> models.ComicImg | None:
    return db.query(models.ComicImg) \
        .filter(
            and_(
                models.ComicImg.chapterid == chapterid,
                models.ComicImg.page == page
            )
    ).first()

@lock(db_lock)
def query_comicimg_by_url(db: Session, comicid: int, url: str) -> models.ComicImg | None:
    chapter = db.query(models.Chapter).filter(
        models.Chapter.comicid == comicid).first()
    if not chapter:
        return None
    return db.query(models.ComicImg) \
        .filter(
            and_(
                models.ComicImg.chapterid == chapter.id,
                models.ComicImg.url == url
            )
    ).first()


@lock(db_lock)
def add_comicimg(db: Session, comicimg: models.ComicImg) -> models.ComicImg:
    db.add(comicimg)
    db.commit()
    db.refresh(comicimg)
    return comicimg

@lock(db_lock)
def query_comicimg_arr(db: Session, img:models.ComicImg, *args) -> tuple:
    return db.query(*args).filter(models.ComicImg.id == img.id).first()

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

    comic = query_comic(db, comicid)
    if not comic:
        comic = add_comic(db, models.Comic(comicid=comicid))

    author = data.get('author', None)
    if author:
        author = ' '.join(author)
    else:
        author = []
    comic = modify_comic(
        db,
        comic,
        url=data.get('url', ''),
        title=data.get('title', ''),
        description=data.get('description', ''),
        page=data.get('page', 0),
        author=author,
        tags=data.get('tags', [])
    )

    # 处理每一章
    nexts = data.get('next', None)
    if nexts:
        for next in nexts:
            next_comic = query_chapter(db, int(next))
            if not next_comic:
                next_comic = add_chapter(db, models.Chapter(comicid=int(next)))
            next_comic = modify_chapter(
                db, next_comic, chapter_num=nexts.index(next) + 1)

            comic = modify_comic(db, comic, chapters=next_comic)

    return True


@lock(db_lock)
def search_data_to_db(db: Session, data: list) -> None:
    """搜索页面解析的数据入数据库

    Args:
        db (Session): 数据库
        data (list): 搜索数据，格式[[id, url],[id, url],...,[id, url]]
    """
    comics = []
    for item in data:
        comic = db.query(models.Comic).filter(
            models.Comic.comicid == int(item[0])).first()
        if not comic:
            comic = models.Comic(comicid=int(item[0]))

        if not comic.url:
            comic.url = item[1]
            comics.append(comic)
    if comics:
        db.add_all(comics)
        db.commit()

'''
other
'''
@lock(db_lock)
def count_percent(db: Session, main_key, tag_key, tag_val) -> float:
    count = db.query(func.count(main_key)).filter(tag_key == tag_val).scalar() 
    total = db.query(func.count(main_key)).scalar()
    return round(count / total * 100, 2)