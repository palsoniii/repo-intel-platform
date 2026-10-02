"""Data-model extraction (app/product/entities.py) -- one test per supported ORM form."""

from app.product.entities import extract_entities


def _by_name(files):
    return {e["name"]: e for e in extract_entities(files)}


def test_typeorm_entity_fields_and_relations():
    src = """
import { Entity, Column, PrimaryGeneratedColumn, ManyToOne, OneToMany } from 'typeorm';

@Entity('article')
export class ArticleEntity {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ default: '' })
  title: string;

  @ManyToOne(type => UserEntity, user => user.articles)
  author: UserEntity;

  @OneToMany(() => Comment, comment => comment.article, { eager: true })
  comments: Comment[];

  updateTimestamp() {
    this.updated = new Date();
  }
}
"""
    e = _by_name({"src/article/article.entity.ts": src})["ArticleEntity"]
    assert e["orm"] == "typeorm"
    assert [f["name"] for f in e["fields"]] == ["id", "title"]
    assert {(r["target"], r["kind"]) for r in e["relations"]} == {("UserEntity", "one"), ("Comment", "many")}


def test_nest_mongoose_schema_class_with_ref():
    src = """
import { Prop, Schema, SchemaFactory } from '@nestjs/mongoose';
import * as mongoose from 'mongoose';

@Schema({ timestamps: true })
export class Cat {
  @Prop({ required: true })
  name: string;

  @Prop({ type: mongoose.Schema.Types.ObjectId, ref: 'Owner' })
  owner: Owner;
}
"""
    e = _by_name({"src/cats/cat.schema.ts": src})["Cat"]
    assert e["orm"] == "mongoose"
    assert [f["name"] for f in e["fields"]] == ["name", "owner"]
    assert e["relations"] == [{"target": "Owner", "kind": "one", "field": "owner"}]


def test_plain_mongoose_schema_named_by_model_call():
    src = """
const mongoose = require('mongoose');
const userSchema = mongoose.Schema({
  name: { type: String, required: true, trim: true },
  email: String,
  posts: [{ type: mongoose.Schema.Types.ObjectId, ref: 'Post' }],
  // role: String,
});
const User = mongoose.model('User', userSchema);
module.exports = User;
"""
    e = _by_name({"src/models/user.model.js": src})["User"]
    assert [(f["name"], f["type"]) for f in e["fields"]] == [
        ("name", "String"), ("email", "String"), ("posts", "ObjectId[]"),
    ]
    assert e["relations"] == [{"target": "Post", "kind": "many", "field": "posts"}]


def test_sequelize_define_and_associations():
    files = {
        "app/models/tutorial.model.js": """
module.exports = (sequelize, Sequelize) => {
  const Tutorial = sequelize.define("tutorial", {
    title: { type: Sequelize.STRING },
    published: { type: Sequelize.BOOLEAN }
  });
  return Tutorial;
};
""",
        "app/models/comment.model.js": """
module.exports = (sequelize, DataTypes) => sequelize.define("comment", { text: DataTypes.TEXT });
""",
        "app/models/index.js": """
const Sequelize = require("sequelize");
db.tutorial.hasMany(db.comment);
""",
    }
    entities = _by_name(files)
    assert [(f["name"], f["type"]) for f in entities["tutorial"]["fields"]] == [
        ("title", "STRING"), ("published", "BOOLEAN"),
    ]
    # `db.tutorial.hasMany(db.comment)` resolves both sides case-insensitively.
    assert entities["tutorial"]["relations"] == [{"target": "comment", "kind": "many", "field": ""}]


def test_prisma_models_split_scalars_from_relations():
    schema = """
model User {
  id    String @id @default(cuid())
  email String @unique
  posts Post[]
  @@map("users")
}

model Post {
  id       String  @id
  author   User?   @relation(fields: [authorId], references: [id])
  authorId String?
}
"""
    entities = _by_name({"prisma/schema.prisma": schema})
    assert [f["name"] for f in entities["User"]["fields"]] == ["id", "email"]
    assert entities["User"]["relations"] == [{"target": "Post", "kind": "many", "field": "posts"}]
    assert entities["Post"]["relations"] == [{"target": "User", "kind": "one", "field": "author"}]


def test_graphql_schema_decorator_is_not_a_model():
    src = """
import { Schema } from 'some-graphql-lib';
@Schema()
export class NotAModel { @Field() name: string; }
"""
    assert extract_entities({"src/x.ts": src}) == []
