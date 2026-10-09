// 求斐波那契数列前 n 项
function fibonacci(n) {
  const result = [];
  for (let i = 0; i < n; i++) {
    result.push(i < 2 ? 1 : result[i - 1] + result[i - 2]);
  }
  return result;
}

console.log(fibonacci(10));
