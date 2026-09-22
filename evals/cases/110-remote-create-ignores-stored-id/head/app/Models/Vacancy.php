<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

final class Vacancy extends Model
{
    protected $fillable = [
        'title',
        'description',
        'salary',
        'job_board_id',
        'published_at',
    ];
}
