import { Controller, Get, Post, Body, Param } from '@nestjs/common';
import { UsersService } from './users.service';

@Controller('users')
export class UsersController {
  constructor(private readonly usersService: UsersService) {}

  @Get()
  findAll() {
    return this.usersService.find('');
  }

  @Get(':id')
  findOne(@Param('id') id: string) {
    return this.usersService.find(id);
  }

  @Post()
  create(@Body() name: string) {
    return this.usersService.create(name);
  }
}
