<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\Vacancy;

final class VacancyRepository
{
    public function storeBoardId(Vacancy $vacancy, int $boardId): Vacancy
    {
        $vacancy->job_board_id = $boardId;
        $vacancy->save();

        return $vacancy;
    }
}
