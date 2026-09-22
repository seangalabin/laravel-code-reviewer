<?php

declare(strict_types=1);

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

final class Booking extends Model
{
    protected $fillable = [
        'reference',
        'starts_at',
        'customer_phone',
        'last_reminder_message_id',
        'last_reminder_sent_at',
    ];

    protected $casts = [
        'starts_at' => 'datetime',
        'last_reminder_sent_at' => 'datetime',
    ];
}
