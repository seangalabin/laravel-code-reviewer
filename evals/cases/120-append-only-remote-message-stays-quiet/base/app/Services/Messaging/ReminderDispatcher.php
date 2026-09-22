<?php

declare(strict_types=1);

namespace App\Services\Messaging;

use App\Models\Booking;

final class ReminderDispatcher
{
    public function __construct(private readonly Client $client)
    {
    }

    public function previewReminder(Booking $booking): string
    {
        return "Reminder: booking {$booking->reference} starts at {$booking->starts_at->format('g:ia')}.";
    }
}
