from typing import Optional, List
from datetime import datetime

from sqlmodel import Field, SQLModel, Relationship, Column, String, Text
from sqlalchemy import Index


class PostTagLink(SQLModel, table=True):
    __tablename__ = "_PostTags"
    A: int = Field(foreign_key="Post.id", primary_key=True)
    B: int = Field(foreign_key="Tag.id", primary_key=True)


class PostIoCLink(SQLModel, table=True):
    __tablename__ = "_PostIoCs"
    A: int = Field(foreign_key="IoC.id", primary_key=True)
    B: int = Field(foreign_key="Post.id", primary_key=True)


class Tag(SQLModel, table=True):
    __tablename__ = "Tag"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String(255), unique=True, index=True))
    color: str = Field(default="#000", sa_column=Column(String(13)))

    posts: List["Post"] = Relationship(back_populates="tags", link_model=PostTagLink)


class IoC(SQLModel, table=True):
    __tablename__ = "IoC"
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(sa_column=Column(String(255)))
    subtype: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    value: str = Field(sa_column=Column(String(512)))
    comment: Optional[str] = Field(default=None, sa_column=Column(Text))

    posts: List["Post"] = Relationship(back_populates="iocs", link_model=PostIoCLink)


class Post(SQLModel, table=True):
    __tablename__ = "Post"
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: Optional[str] = Field(default=None)
    source: str = Field(sa_column=Column(String(255)))
    user: str = Field(sa_column=Column(String(255)))
    created_at: datetime
    fetched_at: datetime
    url: str = Field(sa_column=Column(String(512)))
    content_html: str = Field(sa_column=Column(Text))
    content_txt: str = Field(sa_column=Column(Text))
    content_search: Optional[str] = Field(default=None, sa_column=Column(Text))
    raw: str = Field(sa_column=Column(Text))
    tags_assigned: bool = Field(default=False)
    iocs_assigned: bool = Field(default=False)
    is_hidden: bool = Field(default=True)
    is_ingested: bool = Field(default=False)

    tags: List[Tag] = Relationship(back_populates="posts", link_model=PostTagLink)
    iocs: List[IoC] = Relationship(back_populates="posts", link_model=PostIoCLink)


class SearchCache(SQLModel, table=True):
    __tablename__ = "SearchCache"
    id: Optional[int] = Field(default=None, primary_key=True)
    query_hash: str = Field(sa_column=Column(String(255), unique=True))
    query: str = Field(sa_column=Column(Text))
    filepath: str = Field(sa_column=Column(String(512), unique=True))
    expires_at: datetime
