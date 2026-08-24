const express = require('express');
const router = express.Router();

// A plain middleware mount (not a same-file router) -- must not be misread as
// "a router built in this file" and corrupt this module's own mount prefix.
router.use('/docs', express.static('docs'));

function listUsers(req, res) {
  res.json([]);
}

function createUser(req, res) {
  res.status(201).send();
}

router.get('/', listUsers);
router.post('/', createUser);
router.delete('/:id', function(req, res) {
  res.status(204).send();
});

module.exports = router;
