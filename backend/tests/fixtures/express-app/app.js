const express = require('express');
const usersRouter = require('./routes/users');
const app = express();

app.use('/api/users', usersRouter);

app.get('/health', (req, res) => {
  res.send('ok');
});

module.exports = app;
