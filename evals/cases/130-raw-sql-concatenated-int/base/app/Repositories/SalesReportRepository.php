<?php

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

class SalesReportRepository
{
    public function totalsForYear(int $year): array
    {
        return DB::select(
            'SELECT MONTH(created_at) AS month, SUM(total) AS total
             FROM orders
             WHERE YEAR(created_at) = ?
             GROUP BY MONTH(created_at)',
            [$year]
        );
    }
}
