<?php

declare(strict_types=1);

namespace App\Services;

final class NotifierService
{
    public function __construct(
        private readonly \Illuminate\Http\Client\Factory $http,
    ) {}

    public function notifyOpsChannel(string $message): void
    {
        $this->http
            ->timeout(10)
            ->post(config('services.slack.ops_webhook'), ['text' => $message]);
    }
}
