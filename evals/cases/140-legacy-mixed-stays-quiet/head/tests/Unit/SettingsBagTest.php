<?php

declare(strict_types=1);

use App\Support\SettingsBag;

it('returns a stored null instead of the default', function () {
    $bag = new SettingsBag(['timezone' => null]);

    expect($bag->get('timezone', 'UTC'))->toBeNull();
});

it('falls back to the default for a missing key', function () {
    expect((new SettingsBag())->get('timezone', 'UTC'))->toBe('UTC');
});

it('reads through array access', function () {
    $bag = new SettingsBag(['locale' => 'en_AU']);

    expect(isset($bag['locale']))->toBeTrue()
        ->and($bag['locale'])->toBe('en_AU');
});

it('is read-only through array access', function () {
    $bag = new SettingsBag();

    expect(fn () => $bag['locale'] = 'fr')->toThrow(LogicException::class);
});
