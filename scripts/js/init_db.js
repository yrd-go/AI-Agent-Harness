/**
 * init_db.js
 * 使用 Node.js 内置 node:sqlite 创建 test.db，
 * 建表 students(id, name) 并插入 3 条数据。
 */
const { DatabaseSync } = require("node:sqlite");

const db = new DatabaseSync("test.db");

// 建表（IF NOT EXISTS 保证可重复执行）
db.exec(`
  CREATE TABLE IF NOT EXISTS students (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
  );
`);

// 插入 3 条数据
const insert = db.prepare("INSERT INTO students (id, name) VALUES (?, ?)");
insert.run(1, "张三");
insert.run(2, "李四");
insert.run(3, "王五");

console.log("已创建 test.db 并插入 3 条数据：1 张三，2 李四，3 王五");

db.close();
