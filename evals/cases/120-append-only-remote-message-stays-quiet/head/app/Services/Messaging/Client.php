<?php

declare(strict_types=1);

namespace App\Services\Messaging;

use Illuminate\Support\Facades\Http;

final class Client
{
    public function sendMessage(string $to, string $body): array
    {
        return Http::withToken(config('services.messaging.token'))
            ->baseUrl(config('services.messaging.url'))
            ->timeout(30)
            ->asJson()
            ->post('/messages', ['to' => $to, 'body' => $body])
            ->throw()
            ->json();
    }
}
