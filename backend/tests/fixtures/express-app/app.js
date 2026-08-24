const express = require('express');
const usersRouter = require('./routes/users');
const app = express();

app.use('/api/users', usersRouter);

app.get('/health', (req, res) => {
  res.send('ok');
});

app.set('port', process.env.PORT || 3000);
app.listen(app.get('port'));

module.exports = app;
