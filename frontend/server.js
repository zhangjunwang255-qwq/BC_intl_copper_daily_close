/**
 * 静态文件服务器 + API 反向代理
 * Railway 部署入口，代理 /api/* 请求到后端
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = process.env.PORT || 3000;
// Railway 内部服务名，或外部 URL
const API_TARGET = process.env.API_TARGET || 'http://backend:8080';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

function sendFile(res, filePath, ext) {
  const mime = MIME[ext] || 'application/octet-stream';
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
      return;
    }
    res.writeHead(200, { 'Content-Type': mime });
    res.end(data);
  });
}

function proxyApi(req, res) {
  const target = API_TARGET + req.url;
  const parsedUrl = url.parse(req.url);
  const options = {
    hostname: new URL(API_TARGET).hostname,
    port: new URL(API_TARGET).port,
    path: parsedUrl.path,
    method: req.method,
    headers: {
      ...req.headers,
      host: new URL(API_TARGET).host,
    },
  };
  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, {
      ...proxyRes.headers,
      'Access-Control-Allow-Origin': '*',
    });
    proxyRes.pipe(res);
  });
  proxyReq.on('error', (e) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Backend unavailable' }));
  });
  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  // CORS 预检
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    });
    res.end();
    return;
  }

  // API 代理
  if (req.url.startsWith('/api/')) {
    return proxyApi(req, res);
  }

  // 静态文件
  let urlPath = req.url.split('?')[0];
  if (urlPath === '/') urlPath = '/index.html';
  const filePath = path.join(__dirname, urlPath);
  const ext = path.extname(filePath).toLowerCase();
  sendFile(res, filePath, ext);
});

server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log(`API proxy → ${API_TARGET}`);
});
