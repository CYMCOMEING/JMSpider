from sqlalchemy import Column, Integer, String, DateTime, func

from database.database import Base


class Comic(Base):
    __tablename__ = 'comics'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键自动增长
    comicid = Column(String, nullable=None, unique=True)  # 漫画id 不可为空且唯一
    title = Column(String, default='')  # 漫画标题
    chapter_titile = Column(String, default='') # 每章标题
    url = Column(String, default='')  # 漫画链接
    tags = Column(String, default='')  # 标签，空格隔开
    description = Column(String, default='')  # 漫画描述
    page = Column(Integer, default=0)  # 总页数，所有话
    curr_page = Column(Integer, default=0)  # 本章页数
    next = Column(String, default='')  # 下一话，空格隔开
    static = Column(Integer, default=0)  # 状态，0下载中，1未整理，2通过，3黑名单，4喜爱
    create_time = Column(DateTime, default=func.now())  # 自动添加时间

    def __repr__(self):
        return f'<Comic(id={self.id}, comicid={self.comicid}, title={self.title}, \
chapter_titile={self.chapter_titile}, url={self.url}, tags={self.tags}, \
description={self.description}, page={self.page}, curr_page={self.curr_page}, next={self.next}, \
static={self.static}, create_time={self.create_time})>'
