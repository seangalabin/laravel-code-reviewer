<?php

declare(strict_types=1);

namespace App\Services\JobBoard;

use Illuminate\Support\Facades\Http;

final class Client
{
    public function createVacancy(array $payload): array
    {
        return $this->request()->post('/vacancies', $payload)->throw()->json();
    }

    public function updateVacancy(int $vacancyId, array $payload): array
    {
        return $this->request()->put("/vacancies/{$vacancyId}", $payload)->throw()->json();
    }

    public function getVacancy(int $vacancyId): array
    {
        return $this->request()->get("/vacancies/{$vacancyId}")->throw()->json();
    }

    private function request(): \Illuminate\Http\Client\PendingRequest
    {
        return Http::withToken(config('services.job_board.token'))
            ->baseUrl(config('services.job_board.url'))
            ->timeout(30)
            ->asJson();
    }
}
