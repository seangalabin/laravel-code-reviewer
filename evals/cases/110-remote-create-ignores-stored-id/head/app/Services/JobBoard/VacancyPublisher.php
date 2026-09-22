<?php

declare(strict_types=1);

namespace App\Services\JobBoard;

use App\Models\Vacancy;
use App\Repositories\VacancyRepository;
use RuntimeException;

final class VacancyPublisher
{
    public function __construct(
        private readonly Client $client,
        private readonly VacancyRepository $vacancies,
    ) {
    }

    public function upsertVacancy(Vacancy $vacancy): Vacancy
    {
        $response = $this->client->createVacancy([
            'title' => $vacancy->title,
            'description' => $vacancy->description,
            'salary' => $vacancy->salary,
        ]);

        $boardId = $response['VacancyId'] ?? null;

        if (! is_int($boardId)) {
            throw new RuntimeException("Job board returned no vacancy id for vacancy {$vacancy->id}.");
        }

        return $this->vacancies->storeBoardId($vacancy, $boardId);
    }
}
