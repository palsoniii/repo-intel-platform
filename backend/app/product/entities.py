"""
Data-model extraction: finds the ORM models a repository defines and the relations
between them, for the dashboard's Data Models view.

ParsedRepository has always declared `database_entities`, and neither parser fills it
(README, "Known limitations"). This module fills that gap for the product only -- it
runs over the stored source text after parsing and does not change parser output, so
the evaluation's ground truth is unaffected.

Covered: Mongoose (`new Schema({...})` and NestJS `@Schema()` classes), TypeORM
(`@Entity()`), sequelize-typescript (`@Table`), Sequelize (`sequelize.define` and
`Model.init`) and Prisma (`schema.prisma`). Anything else is simply not found.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.product.jsscan import line_of, match_bracket, strip_comments, top_level_entries


@dataclass
class EntityField:
    name: str
    type: str


@dataclass
class EntityRelation:
    target: str
    kind: str  # "one" | "many"
    field: str


@dataclass
class Entity:
    name: str
    orm: str
    source_path: str
    line: int
    fields: list[EntityField] = field(default_factory=list)
    relations: list[EntityRelation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Decorator-based classes: TypeORM, NestJS-Mongoose, sequelize-typescript
# ---------------------------------------------------------------------------

_CLASS_DECORATORS = {"Entity": "typeorm", "Schema": "mongoose", "Table": "sequelize"}
_FIELD_DECORATORS = {
    "Column", "PrimaryGeneratedColumn", "PrimaryColumn", "CreateDateColumn",
    "UpdateDateColumn", "DeleteDateColumn", "VersionColumn", "ObjectIdColumn",
    "Prop", "ForeignKey", "PrimaryKey", "AutoIncrement", "Unique", "Default",
    "AllowNull", "CreatedAt", "UpdatedAt", "DeletedAt",
}
_RELATION_DECORATORS = {
    "ManyToOne": "one", "OneToOne": "one", "OneToMany": "many", "ManyToMany": "many",
    "BelongsTo": "one", "HasOne": "one", "HasMany": "many", "BelongsToMany": "many",
}
_DECORATED_CLASS_RE = re.compile(
    r"@(?P<deco>Entity|Schema|Table)\s*\(", re.MULTILINE
)
_CLASS_HEADER_RE = re.compile(r"\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)[^{]*\{")
_DECORATOR_RE = re.compile(r"@(?P<name>\w+)\s*\(")
_PROPERTY_RE = re.compile(
    r"\s*(?:(?:public|private|protected|readonly|declare|override)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*[?!]?\s*:\s*(?P<type>[^;=\n]+)"
)
_ARROW_TARGET_RE = re.compile(r"(?:\(\s*\w*\s*\)|\w+)\s*=>\s*\[?\s*(?P<t>\w+)")
_REF_RE = re.compile(r"""ref\s*:\s*(?:['"](?P<s>\w+)['"]|(?P<id>\w+)\.name)""")


def _decorated_classes(path: str, text: str) -> list[Entity]:
    clean = strip_comments(text)
    entities: list[Entity] = []
    for m in _DECORATED_CLASS_RE.finditer(clean):
        args_end = match_bracket(clean, m.end() - 1)
        if args_end is None:
            continue
        # Other class decorators (@ObjectType(), @Index(...)) may sit between this
        # one and the class keyword.
        pos = args_end + 1
        while True:
            nxt = re.match(r"\s*@\w+(?:\.\w+)*\s*", clean[pos:])
            if not nxt:
                break
            pos += nxt.end()
            if pos < len(clean) and clean[pos] == "(":
                close = match_bracket(clean, pos)
                if close is None:
                    break
                pos = close + 1
        header = _CLASS_HEADER_RE.match(clean, pos)
        if not header:
            continue
        body_open = header.end() - 1
        body_close = match_bracket(clean, body_open)
        if body_close is None:
            continue
        orm = _CLASS_DECORATORS[m.group("deco")]
        # `@Schema` alone is too common a word (GraphQL, Swagger); require Mongoose.
        if orm == "mongoose" and "@nestjs/mongoose" not in clean and "mongoose" not in clean:
            continue
        if orm == "sequelize" and "sequelize-typescript" not in clean:
            continue
        entity = Entity(
            name=header.group("name"), orm=orm, source_path=path, line=line_of(clean, m.start())
        )
        _scan_class_body(clean[body_open + 1 : body_close], entity)
        entities.append(entity)
    return entities


def _scan_class_body(body: str, entity: Entity) -> None:
    pos = 0
    pending: list[tuple[str, str]] = []
    n = len(body)
    while pos < n:
        deco = _DECORATOR_RE.match(body, pos) if body[pos] == "@" else None
        if deco:
            close = match_bracket(body, deco.end() - 1)
            if close is None:
                return
            pending.append((deco.group("name"), body[deco.end() : close]))
            pos = close + 1
            continue
        if pending and not body[pos].isspace():
            prop = _PROPERTY_RE.match(body, pos)
            if prop:
                names = {d for d, _ in pending}
                prop_name = prop.group("name")
                prop_type = prop.group("type").strip()
                relation = next((d for d in names if d in _RELATION_DECORATORS), None)
                if relation:
                    args = next(a for d, a in pending if d == relation)
                    target = _ARROW_TARGET_RE.search(args)
                    entity.relations.append(
                        EntityRelation(
                            target=target.group("t") if target else _bare_type(prop_type),
                            kind=_RELATION_DECORATORS[relation],
                            field=prop_name,
                        )
                    )
                elif names & _FIELD_DECORATORS:
                    entity.fields.append(EntityField(name=prop_name, type=_bare_type(prop_type)))
                    ref = next((_REF_RE.search(a) for d, a in pending if d == "Prop" and _REF_RE.search(a)), None)
                    if ref:
                        entity.relations.append(
                            EntityRelation(
                                target=ref.group("s") or ref.group("id"),
                                kind="many" if prop_type.endswith("[]") else "one",
                                field=prop_name,
                            )
                        )
                pos = prop.end()
            else:
                pos += 1
            pending = []
            continue
        if body[pos] == "{":
            # A method body; skip it whole so its statements aren't read as fields.
            close = match_bracket(body, pos)
            pos = (close + 1) if close is not None else n
            continue
        pos += 1


def _bare_type(type_text: str) -> str:
    t = type_text.strip().rstrip(";").strip()
    t = re.sub(r"\s*\|\s*(null|undefined)\b", "", t)
    t = re.sub(r"^(?:Promise|Array|Ref|Relation|Collection)<(.+)>$", r"\1", t)
    return t or "unknown"


# ---------------------------------------------------------------------------
# Mongoose (plain JavaScript)
# ---------------------------------------------------------------------------

_MONGOOSE_SCHEMA_RE = re.compile(
    r"(?:(?:const|let|var)\s+(?P<var>\w+)\s*=\s*)?(?:new\s+(?:mongoose\.|Mongoose\.)?|mongoose\.)Schema\s*(?:<[^>]*>)?\s*\("
)
_MONGOOSE_MODEL_RE = re.compile(
    r"""(?:mongoose\.|connection\.|db\.)?model\s*(?:<[^>]*>)?\s*\(\s*['"`](?P<name>\w+)['"`]\s*,\s*(?P<var>\w+)"""
)


def _mongoose_models(path: str, text: str) -> list[Entity]:
    if "Schema" not in text or "mongoose" not in text:
        return []
    clean = strip_comments(text)
    var_to_model = {m.group("var"): m.group("name") for m in _MONGOOSE_MODEL_RE.finditer(clean)}
    entities: list[Entity] = []
    for m in _MONGOOSE_SCHEMA_RE.finditer(clean):
        obj_open = clean.find("{", m.end())
        if obj_open == -1 or clean[m.end() : obj_open].strip():
            continue
        obj_close = match_bracket(clean, obj_open)
        if obj_close is None:
            continue
        var = m.group("var")
        name = var_to_model.get(var or "") or _name_from_var_or_path(var, path)
        entity = Entity(name=name, orm="mongoose", source_path=path, line=line_of(clean, m.start()))
        for key, value in top_level_entries(clean[obj_open + 1 : obj_close]):
            entity.fields.append(EntityField(name=key, type=_mongoose_type(value)))
            ref = _REF_RE.search(value)
            if ref:
                entity.relations.append(
                    EntityRelation(
                        target=ref.group("s") or ref.group("id"),
                        kind="many" if value.lstrip().startswith("[") else "one",
                        field=key,
                    )
                )
        entities.append(entity)
    return entities


def _mongoose_type(value: str) -> str:
    v = value.strip()
    many = v.startswith("[")
    m = re.search(r"type\s*:\s*\[?\s*([\w.]+)", v) or re.match(r"\[?\s*([\w.]+)", v)
    t = m.group(1).split(".")[-1] if m else "Mixed"
    if t[:1].islower() and t not in {"true", "false"}:
        t = "Object"
    return f"{t}[]" if many else t


def _name_from_var_or_path(var: str | None, path: str) -> str:
    if var:
        base = re.sub(r"(?i)schema$", "", var) or var
    else:
        base = re.sub(r"\.(model|schema|entity)$", "", path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    return base[:1].upper() + base[1:]


# ---------------------------------------------------------------------------
# Sequelize (plain JavaScript)
# ---------------------------------------------------------------------------

_SEQ_DEFINE_RE = re.compile(r"""\.define\s*\(\s*['"`](?P<name>\w+)['"`]\s*,\s*\{""")
_SEQ_INIT_RE = re.compile(r"(?P<name>\w+)\.init\s*\(\s*\{")
_SEQ_ASSOC_RE = re.compile(
    r"(?:models\.|db\.)?(?P<src>\w+)\.(?P<kind>belongsTo|hasMany|hasOne|belongsToMany)\s*\(\s*"
    r"(?:models\.|db\.|this\.sequelize\.models\.)?(?P<dst>\w+)"
)
_SEQ_ASSOC_KIND = {"belongsTo": "one", "hasOne": "one", "hasMany": "many", "belongsToMany": "many"}


def _sequelize_models(path: str, text: str) -> list[Entity]:
    if "sequelize" not in text.lower():
        return []
    clean = strip_comments(text)
    entities: list[Entity] = []
    for regex in (_SEQ_DEFINE_RE, _SEQ_INIT_RE):
        for m in regex.finditer(clean):
            if regex is _SEQ_INIT_RE and not re.search(
                rf"class\s+{re.escape(m.group('name'))}\s+extends\s+(?:Sequelize\.)?Model", clean
            ):
                continue
            obj_open = m.end() - 1
            obj_close = match_bracket(clean, obj_open)
            if obj_close is None:
                continue
            entity = Entity(
                name=m.group("name"), orm="sequelize", source_path=path, line=line_of(clean, m.start())
            )
            for key, value in top_level_entries(clean[obj_open + 1 : obj_close]):
                t = re.search(r"(?:DataTypes|Sequelize|DataType)\.(\w+)", value)
                entity.fields.append(EntityField(name=key, type=t.group(1) if t else "unknown"))
            entities.append(entity)
    return entities


def _sequelize_associations(text: str) -> list[tuple[str, str, str]]:
    return [
        (m.group("src"), m.group("dst"), _SEQ_ASSOC_KIND[m.group("kind")])
        for m in _SEQ_ASSOC_RE.finditer(strip_comments(text))
    ]


# ---------------------------------------------------------------------------
# Prisma
# ---------------------------------------------------------------------------

_PRISMA_MODEL_RE = re.compile(r"^model\s+(?P<name>\w+)\s*\{(?P<body>[^}]*)\}", re.MULTILINE)
_PRISMA_SCALARS = {
    "String", "Int", "BigInt", "Float", "Decimal", "Boolean", "DateTime", "Json", "Bytes",
}


def _prisma_models(path: str, text: str) -> list[Entity]:
    models = list(_PRISMA_MODEL_RE.finditer(text))
    names = {m.group("name") for m in models}
    entities: list[Entity] = []
    for m in models:
        entity = Entity(name=m.group("name"), orm="prisma", source_path=path, line=line_of(text, m.start()))
        for raw_line in m.group("body").splitlines():
            line = raw_line.split("//", 1)[0].strip()
            if not line or line.startswith("@@"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            fname, ftype = parts[0], parts[1]
            base = ftype.rstrip("?[]")
            if base in names:
                entity.relations.append(
                    EntityRelation(target=base, kind="many" if ftype.endswith("[]") else "one", field=fname)
                )
            else:
                entity.fields.append(EntityField(name=fname, type=ftype))
        entities.append(entity)
    return entities


# ---------------------------------------------------------------------------


def extract_entities(files: dict[str, str]) -> list[dict]:
    """files: repo-relative path -> source text. Returns plain dicts (JSON-ready)."""
    entities: list[Entity] = []
    associations: list[tuple[str, str, str]] = []
    for path, text in sorted(files.items()):
        if path.endswith(".prisma"):
            entities.extend(_prisma_models(path, text))
            continue
        if not path.endswith((".js", ".ts", ".mjs", ".cjs")):
            continue
        if "@Entity" in text or "@Schema" in text or "@Table" in text:
            entities.extend(_decorated_classes(path, text))
        entities.extend(_mongoose_models(path, text))
        entities.extend(_sequelize_models(path, text))
        if "belongsTo" in text or "hasMany" in text or "hasOne" in text:
            associations.extend(_sequelize_associations(text))

    # The same model is sometimes declared twice (a schema file plus a typed wrapper);
    # keep the declaration with the most fields.
    by_name: dict[str, Entity] = {}
    for e in entities:
        existing = by_name.get(e.name)
        if existing is None or len(e.fields) > len(existing.fields):
            by_name[e.name] = e

    lookup = {name.lower(): name for name in by_name}
    for src, dst, kind in associations:
        s, d = lookup.get(src.lower()), lookup.get(dst.lower())
        if s and d and not any(r.target == d for r in by_name[s].relations):
            by_name[s].relations.append(EntityRelation(target=d, kind=kind, field=""))

    for e in by_name.values():
        # Relation targets are often written as the class/variable name; normalise
        # them onto entity names where a case-insensitive match exists.
        for r in e.relations:
            target = r.target.rstrip("[]")
            r.target = lookup.get(target.lower(), target)

    return [asdict(e) for e in sorted(by_name.values(), key=lambda e: (e.source_path, e.line))]
