import { Injectable } from '@nestjs/common';

@Injectable()
export class UsersService {
  find(id: string) {
    return id;
  }
}
