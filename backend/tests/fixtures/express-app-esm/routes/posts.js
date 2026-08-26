// Written in ES module syntax, unlike app.js -- real repos mix styles mid-migration,
// or use a bundler/Node's native ESM support for newer files. Before this fix, a
// file written this way had an entirely empty imports list, since only require()
// calls were ever extracted.
import { Router } from 'express';
import { createPost } from '../services/postService.js';

const router = Router();
router.get('/', createPost);

export default router;
