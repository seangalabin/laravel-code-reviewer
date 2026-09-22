<?php

declare(strict_types=1);

namespace App\Services\Messaging;

use App\Models\Booking;
use RuntimeException;

final class ReminderDispatcher
{
    public function __construct(private readonly Client $client)
    {
    }

    public function previewReminder(Booking $booking): string
    {
        return "Reminder: booking {$booking->reference} starts at {$booking->starts_at->format('g:ia')}.";
    }

    /**
     * Send a reminder for this booking. Each send is its own message on the
     * provider — a second reminder is a second message, by design — so the
     * booking keeps only the most recent message id, for support lookups.
     */
    public function sendReminder(Booking $booking): Booking
    {
        $response = $this->client->sendMessage(
            $booking->customer_phone,
            $this->previewReminder($booking),
        );

        $messageId = $response['message_id'] ?? null;

        if (! is_string($messageId) || $messageId === '') {
            throw new RuntimeException("Messaging provider returned no message id for booking {$booking->reference}.");
        }

        $booking->forceFill([
            'last_reminder_message_id' => $messageId,
            'last_reminder_sent_at' => now(),
        ])->save();

        return $booking;
    }
}
