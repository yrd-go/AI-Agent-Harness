const http = require('http');

const employees = {
  '1001': '张三',
  '1002': '李四'
};

const server = http.createServer((req, res) => {
  const id = req.url.split('/').pop() || '';
  const employee = employees[id];
  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end(employee || 'Not found');
});

server.listen(3001, () => {
  console.log('Server running on port 3001');
});