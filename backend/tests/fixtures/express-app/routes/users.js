const express = require('express');
const router = express.Router();

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
