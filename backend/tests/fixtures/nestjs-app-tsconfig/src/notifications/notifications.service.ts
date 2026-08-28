import { Injectable } from '@nestjs/common';
// Imported via the tsconfig '@app/*' alias rather than a relative
// '../users/users.service' path -- before this fix, a non-relative import
// like this was always treated as an unresolvable external package.
import { UsersService } from '@app/users/users.service';

@Injectable()
export class NotificationsService {
  constructor(private readonly usersService: UsersService) {}
}
