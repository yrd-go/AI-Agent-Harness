/**
 * query_student.js
 * 查询 test.db 中 students 表里 id 为 2 的学生名字。
 */
const { DatabaseSync } = require("node:sqlite");

const db = new DatabaseSync("test.db");

const row = db.prepare("SELECT name FROM students WHERE id = ?").get(2);

if (row) {
  console.log(`id 为 2 的学生名字是：${row.name}`);
} else {
  console.log("未找到 id 为 2 的学生。");
}

db.close();
