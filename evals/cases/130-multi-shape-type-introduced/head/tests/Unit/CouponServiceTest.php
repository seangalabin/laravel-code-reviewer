<?php

declare(strict_types=1);

use App\Models\Coupon;
use App\Services\CouponService;

it('returns false for an unknown coupon', function () {
    expect(app(CouponService::class)->applyCoupon('NOPE', 10_000))->toBeFalse();
});

it('returns false for an expired coupon', function () {
    Coupon::factory()->expired()->create(['code' => 'OLD']);

    expect(app(CouponService::class)->applyCoupon('OLD', 10_000))->toBeFalse();
});

it('applies a percentage coupon', function () {
    $coupon = Coupon::factory()->percentage(15)->create(['code' => 'PCT']);

    $result = app(CouponService::class)->applyCoupon('PCT', 10_000);

    expect($result['coupon_id'])->toBe($coupon->id)
        ->and($result['discount']->kind)->toBe('percentage')
        ->and($result['discount']->value)->toBe(15);
});

it('applies a fixed coupon', function () {
    Coupon::factory()->fixed(500, 'AUD')->create(['code' => 'FIX']);

    $result = app(CouponService::class)->applyCoupon('FIX', 10_000);

    expect($result['discount']->kind)->toBe('fixed')
        ->and($result['discount']->value)->toBe(['amount_cents' => 500, 'currency' => 'AUD']);
});
