import { Injectable } from '@nestjs/common';

@Injectable()
export class AppService {
  getHealth() {
    return { servico: 'avaliacoes', status: 'ok' };
  }
}
