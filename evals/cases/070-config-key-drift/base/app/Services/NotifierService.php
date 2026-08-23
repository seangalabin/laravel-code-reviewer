<?php

declare(strict_types=1);

namespace App\Services;

final class NotifierService
{
    public function __construct(
        private readonly \Illuminate\Http\Client\Factory $http,
    ) {}
}
