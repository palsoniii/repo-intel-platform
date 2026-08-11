// Test file inside a test directory: must be excluded from modules, but recorded
// in files_skipped so the exclusion stays auditable.
const request = require('supertest');
const app = require('../app');

test('lists users', async () => {
  await request(app).get('/api/users').expect(200);
});
