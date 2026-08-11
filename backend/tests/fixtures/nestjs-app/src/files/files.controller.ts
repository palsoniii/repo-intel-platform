import { Controller, Get, Post, Param } from '@nestjs/common';

// Object-form @Controller: the path lives in an options object alongside other
// metadata (version, host, scope). Real NestJS boilerplates use this form widely --
// brocoders/nestjs-boilerplate declares every controller this way.
@Controller({
  path: 'files',
  version: '1',
})
export class FilesController {
  @Post('upload')
  upload() {
    return { ok: true };
  }

  @Get(':path')
  download(@Param('path') path: string) {
    return { path };
  }
}
