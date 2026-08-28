const express = require('express');
const apiRouter = require('./routes/api');
const app = express();

app.use('/api', apiRouter);

module.exports = app;
