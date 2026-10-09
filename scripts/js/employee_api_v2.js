// employee_api_v2.js — 模拟员工查询脚本
// 用法: node employee_api_v2.js <员工编号>

const employees = {
  '1001': { id: '1001', name: '张三' },
  '1002': { id: '1002', name: '李四' },
};

function queryEmployee(id) {
  return employees[id] || null;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error('用法: node employee_api_v2.js <员工编号>');
    process.exit(1);
  }

  const id = args[0];
  const employee = queryEmployee(id);

  if (employee) {
    console.log(JSON.stringify(employee));
  } else {
    console.log(JSON.stringify({ error: '未找到该员工', id }));
  }
}

main();
