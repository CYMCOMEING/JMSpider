from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship

from database.database import Base


# class Comic_old(Base):
#     __tablename__ = 'comics'

#     id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
#     comicid = Column(String, nullable=None, unique=True)  # 漫画id 不可为空且唯一
#     title = Column(String, default='')  # 漫画标题
#     chapter_titile = Column(String, default='')  # 每章标题
#     url = Column(String, default='')  # 漫画链接
#     tags = Column(String, default='')  # 标签，空格隔开
#     description = Column(String, default='')  # 漫画描述
#     page = Column(Integer, default=0)  # 总页数，所有话
#     curr_page = Column(Integer, default=0)  # 本章页数
#     next = Column(String, default='')  # 下一话，空格隔开
#     static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
#     create_time = Column(DateTime, default=func.now())  # 自动添加时间

#     def __repr__(self):
#         return f'<Comic(id={self.id}, comicid={self.comicid}, title={self.title}, \
# chapter_titile={self.chapter_titile}, url={self.url}, tags={self.tags}, \
# description={self.description}, page={self.page}, curr_page={self.curr_page}, next={self.next}, \
# static={self.static}, create_time={self.create_time})>'


class Comic(Base):
    __tablename__ = 'comic'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    comicid = Column(Integer, unique=True, default=0)  # 禁漫id
    title = Column(String, default='')  # 漫画标题
    chapter_titile = Column(String, default='')  # 每章标题
    url = Column(String, default='')  # 漫画链接
    description = Column(String, default='')  # 漫画描述
    page = Column(Integer, default=0)  # 总页数，所有话
    curr_page = Column(Integer, default=0)  # 本章页数
    static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
    create_time = Column(DateTime, default=func.now())  # 自动添加时间

    chapters = relationship("Chapter", back_populates="comic")
    tags = relationship("Tag", secondary="comic_tag", back_populates="comic")

    def __repr__(self):
        return f'<Comic({self.id}, {self.comicid}, {self.title}, {self.chapter_titile}, {self.url}, {self.description}, {self.page}, {self.curr_page}, {self.static}, {self.create_time}, {self.chapters}, {self.tags})>'


class Chapter(Base):
    __tablename__ = 'chapter'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    main_comic = Column(Integer, ForeignKey('comic.id'))  # 第一话id
    comicid = Column(Integer, unique=True, default=0)  # 禁漫id
    chapter_num = Column(Integer)  # 第几话
    title = Column(String, default='')  # 章节标题
    page = Column(Integer, default=0)  # 本话页数
    static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
    create_time = Column(DateTime, default=func.now())  # 自动添加时间

    # 第一话id，不使用comicid主要是想兼容非禁漫的漫画
    comic = relationship("Comic", back_populates="chapters")

    def __repr__(self):
        return f'<Chapter({self.id}, {self.main_comic}, {self.comicid}, {self.chapter_num}, {self.title}, {self.page}, {self.create_time})>'


class Tag(Base):
    __tablename__ = 'tag'

    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=True, unique=True)  # 不为空且唯一

    comic = relationship("Comic", secondary="comic_tag", back_populates="tags")

    def __repr__(self):
        return f'<Tag({self.text})>'

# 多对多关联表


class Comic_Tag(Base):
    __tablename__ = 'comic_tag'

    id = Column(Integer, primary_key=True)
    comicid = Column(Integer, ForeignKey('comic.id'))
    tagid = Column(Integer, ForeignKey('tag.id'))

# TODO 搞清关系是什么，怎么用sql语句实现
