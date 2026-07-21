import { Injectable } from '@nestjs/common';

export interface UserRepository {
  find(id: string): unknown;
}

@Injectable()
export class UsersService implements UserRepository {
  private readonly users: string[] = [];

  find(id: string) {
    return this.users.find((u) => u === id);
  }

  create(name: string) {
    this.users.push(name);
    return name;
  }
}
