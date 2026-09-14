<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Shipment;
use App\Repositories\ShipmentRepository;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use RuntimeException;

final class ShipmentService
{
    public function __construct(private readonly ShipmentRepository $shipments)
    {
    }

    public function book(int $orderId, string $carrier): Shipment
    {
        return DB::transaction(function () use ($orderId, $carrier): Shipment {
            $shipment = $this->shipments->create($orderId, $carrier);

            $response = Http::timeout(30)
                ->post(config('services.carrier.url').'/bookings', [
                    'order_id' => $orderId,
                    'carrier' => $carrier,
                ])
                ->throw();

            $tracking = $response->json('tracking_number');

            if (! is_string($tracking) || $tracking === '') {
                throw new RuntimeException("Carrier returned no tracking number for order {$orderId}.");
            }

            $this->shipments->markBooked($shipment, $tracking);

            return $shipment;
        });
    }
}
