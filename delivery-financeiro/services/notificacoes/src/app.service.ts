import { Injectable } from '@nestjs/common';

@Injectable()
export class AppService {
  getHealth() {
    return { servico: 'notificacoes', status: 'ok' };
  }
}
