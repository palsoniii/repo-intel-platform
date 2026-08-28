const express = require('express');
const router = express.Router();

// This router is itself mounted by app.js at /api. It then mounts ANOTHER
// router at /v1 -- a two-hop chain (app -> /api -> this file -> /v1 -> the
// v1 router's own routes), which the fix under test must compose fully into
// /api/v1/ping rather than just resolving the innermost /v1/ping.
router.use('/v1', require('./v1/health'));

module.exports = router;
