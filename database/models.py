from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship

from database.database import Base


class Comic(Base):
    __tablename__ = 'comic'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    comicid = Column(Integer, unique=True, default=0)  # 禁漫id
    title = Column(String, default='')  # 漫画标题
    url = Column(String, default='')  # 漫画链接
    description = Column(String, default='')  # 漫画描述
    page = Column(Integer, default=0)  # 总页数，所有话
    static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
    create_time = Column(DateTime, default=func.now())  # 自动添加时间

    chapters = relationship("Chapter", back_populates="comic")
    tags = relationship("Tag", secondary="comic_tag", back_populates="comic")

    def __repr__(self):
        return f'<Comic({self.id}, {self.comicid}, {self.title},{self.url}, {self.description}, {self.page}, {self.static}, {self.create_time})>'


class Chapter(Base):
    __tablename__ = 'chapter'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    main_comic = Column(Integer, ForeignKey(
        'comic.id'))  # 第一话id, TODO 名字改成home
    comicid = Column(Integer, unique=True, default=0)  # 禁漫id
    chapter_num = Column(Integer)  # 第几话
    title = Column(String, default='')  # 章节标题
    page = Column(Integer, default=0)  # 本话页数
    static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
    create_time = Column(DateTime, default=func.now())  # 自动添加时间

    # 第一话id，不使用comicid主要是想兼容非禁漫的漫画
    comic = relationship("Comic", back_populates="chapters")
    imgs = relationship("ComicImg", back_populates="chapter")

    def __repr__(self):
        return f'<Chapter({self.id}, {self.main_comic}, {self.comicid}, {self.chapter_num}, {self.title}, {self.page}, {self.static}, {self.create_time})>'


class ComicImg(Base):
    __tablename__ = 'comicimg'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    chapterid = Column(Integer, ForeignKey('chapter.id'))
    url = Column(String, default='')
    page = Column(Integer, default=0)
    static = Column(Integer, default=0)

    chapter = relationship("Chapter", back_populates="imgs")

    def __repr__(self):
        return f'<ComicImg({self.id}, {self.chapterid}, {self.url}, {self.page}, {self.static})>'


class Tag(Base):
    __tablename__ = 'tag'

    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=True, unique=True)  # 不为空且唯一

    comic = relationship("Comic", secondary="comic_tag", back_populates="tags")

    def __repr__(self):
        return f'<Tag({self.id}, {self.text})>'

# 多对多关联表


class Comic_Tag(Base):
    __tablename__ = 'comic_tag'

    id = Column(Integer, primary_key=True)
    comicid = Column(Integer, ForeignKey('comic.id'))
    tagid = Column(Integer, ForeignKey('tag.id'))