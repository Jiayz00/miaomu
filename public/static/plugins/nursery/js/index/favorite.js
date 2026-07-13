(function(window, $)
{
    'use strict';

    if(!$ || window.__nurseryFavoriteBound === true)
    {
        return;
    }
    window.__nurseryFavoriteBound = true;

    function progressStart()
    {
        if($.AMUI && $.AMUI.progress)
        {
            $.AMUI.progress.start();
        }
    }

    function progressDone()
    {
        if($.AMUI && $.AMUI.progress)
        {
            $.AMUI.progress.done();
        }
    }

    function notify(message, type)
    {
        if(typeof Prompt === 'function')
        {
            Prompt(message, type || undefined);
        }
    }

    function loginRequired()
    {
        if(typeof ModalLoad === 'function')
        {
            ModalLoad(__modal_login_url__, '', 'common-login-modal');
        }
    }

    function updateState(goodsId, active)
    {
        $('.nursery-favorite-action[data-gid="' + goodsId + '"]').each(function()
        {
            var button = $(this);
            button.attr('data-favorite-status', active ? '1' : '0');
            button.data('favorite-status', active ? 1 : 0);
            button.attr('aria-pressed', active ? 'true' : 'false');
            button.toggleClass('am-active', active);
            button.find('.nursery-favorite-text, .name').text(active ? '已收藏' : '收藏');
            button.find('i').toggleClass('icon-heart', active).toggleClass('icon-heart-o', !active);
        });
    }

    function removeCanceledItem(button)
    {
        if(String(button.attr('data-remove-on-cancel')) !== '1')
        {
            return;
        }
        button.closest('.nursery-favorite-item').remove();
        var total = $('[data-favorite-total]');
        if(total.length)
        {
            total.text(Math.max(0, parseInt(total.text(), 10)-1));
        }
        if($('[data-favorite-list] .nursery-favorite-item').length === 0)
        {
            window.location.reload();
        }
    }

    $(document).on('click.nurseryFavorite', '.nursery-favorite-action', function(event)
    {
        event.preventDefault();
        event.stopImmediatePropagation();
        if((window.__user_id__ || 0) === 0)
        {
            loginRequired();
            return false;
        }

        var button = $(this);
        if(button.data('favorite-pending') === true)
        {
            return false;
        }
        var goodsId = String(button.attr('data-gid') || '');
        if(!/^[1-9][0-9]*$/.test(goodsId))
        {
            notify('商品编号无效');
            return false;
        }
        var active = String(button.attr('data-favorite-status')) === '1';
        var url = active ? button.attr('data-cancel-url') : button.attr('data-add-url');
        if(!url)
        {
            notify('收藏服务暂不可用');
            return false;
        }

        button.data('favorite-pending', true).prop('disabled', true).addClass('is-pending');
        progressStart();
        $.ajax({
            url: typeof RequestUrlHandle === 'function' ? RequestUrlHandle(url) : url,
            type: 'post',
            dataType: 'json',
            timeout: 10000,
            data: {
                goods_id: goodsId,
                csrf_token: button.attr('data-csrf-token') || ''
            },
            success: function(response)
            {
                if(response && response.code === 0 && response.data)
                {
                    var nextActive = parseInt(response.data.status, 10) === 1;
                    updateState(goodsId, nextActive);
                    if(!nextActive)
                    {
                        removeCanceledItem(button);
                    }
                    notify(response.msg, 'success');
                } else {
                    if(response && parseInt(response.code, 10) === -400)
                    {
                        loginRequired();
                    } else {
                        notify(response && response.msg ? response.msg : '收藏操作失败');
                    }
                }
            },
            error: function()
            {
                notify('网络请求失败，请稍后重试');
            },
            complete: function()
            {
                progressDone();
                button.data('favorite-pending', false).prop('disabled', false).removeClass('is-pending');
            }
        });
        return false;
    });

    $(document).on('keydown.nurseryFavorite', '.nursery-favorite-action[role="button"]', function(event)
    {
        if(event.key === 'Enter' || event.key === ' ')
        {
            event.preventDefault();
            $(this).trigger('click');
        }
    });
})(window, window.jQuery);
