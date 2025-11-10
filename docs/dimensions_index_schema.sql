CREATE TABLE IF NOT EXISTS "dimensions" (
	"id"	INTEGER,
	"label"	TEXT NOT NULL,
	"dim_code"	INTEGER,
	"file_id"	TEXT NOT NULL,
	"matrix_name"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("label","dim_code","file_id")
);
CREATE TABLE IF NOT EXISTS "options" (
	"id"	INTEGER,
	"label"	TEXT NOT NULL,
	"nom_item_id"	INTEGER,
	"offset_value"	INTEGER,
	"parent_id"	INTEGER,
	"dimension_id"	INTEGER,
	"file_id"	TEXT NOT NULL,
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("label","nom_item_id","dimension_id","file_id"),
	FOREIGN KEY("dimension_id") REFERENCES "dimensions"("id")
);
