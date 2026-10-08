from django.http import JsonResponse


def health_check(request):
    """
    Root health check endpoint.
    """
    return JsonResponse({
        'status': 'healthy',
        'service': 'Factory Traffic Management System API',
        'version': '2.0.0'
    })
